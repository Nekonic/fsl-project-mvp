import { useState } from "preact/hooks";
import { to } from "../../links";
import type { PageProps } from "../../routes";
import { navigate, usePlace } from "../../router";
import { AppPage } from "../../shell/AppPage";
import { t } from "../../strings";
import { Button, Empty, PageBody, Section, Stack, Split } from "../../ui";
import { PostureEditor } from "../../panes/staff/PostureEditor";
import { PostureList } from "../../panes/staff/PostureList";

const NEW_POSTURE = "new";

function postureHref(id: number | typeof NEW_POSTURE): string {
  return `${to.staffPostures()}?id=${id}`;
}

export function Postures(_props: PageProps) {
  const place = usePlace();
  const [changes, setChanges] = useState(0);
  const asked = place.search.get("id");
  const opened = asked === NEW_POSTURE ? null : asked ? Number(asked) : undefined;
  return (
    <AppPage title={t("page.staff.postures")} crumbs={[{ label: t("page.staff.postures") }]}>
      <PageBody>
        <Stack gap="md">
          <Section large title={t("page.staff.postures")}
            actions={<Button tone="primary" href={postureHref(NEW_POSTURE)}>{t("staff.postures.new")}</Button>} />
          <Split list={<PostureList current={opened ?? null} version={changes} hrefOf={postureHref} />}>
            {opened === undefined
              ? <Empty>{t("staff.postures.pick")}</Empty>
              : <PostureEditor key={asked} postureId={opened}
                onSaved={(id) => { setChanges((was) => was + 1); if (id !== opened) navigate(postureHref(id), true); }} />}
          </Split>
        </Stack>
      </PageBody>
    </AppPage>
  );
}
