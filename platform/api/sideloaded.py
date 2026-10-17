import subprocess

from django.http import Http404, StreamingHttpResponse
from django.views.decorators.http import require_GET

from range import substrate, wargame_host

CHUNK = 1 << 20


def _streamed(argv):
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        yield from iter(lambda: process.stdout.read(CHUNK), b"")
    finally:
        process.stdout.close()
        process.kill()
        process.wait()


@require_GET
def sideloaded_image(request, name):
    adapter = substrate()
    image = adapter.sideloaded_image(name) if hasattr(adapter, "sideloaded_image") else ""
    if not image:
        raise Http404(f"no wargame image fsl-{name} is sideloaded on this platform")
    return StreamingHttpResponse(_streamed(wargame_host.saved(image)), content_type="application/x-tar")
