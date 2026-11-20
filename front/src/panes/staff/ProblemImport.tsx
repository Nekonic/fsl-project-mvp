import { useState } from "preact/hooks";
import { api, ApiError } from "../../api/client";
import { errorLine, type ShownError, t } from "../../strings";
import { ErrorList, Notice, FilePick } from "../../ui";
import { readJsonFile, type DocumentBody } from "./document";

export function useProblemImport(onImported: (id: number) => void) {
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<ShownError[]>([]);
  const pick = async (file: File) => {
    setBusy(true);
    setErrors([]);
    try {
      const doc = await readJsonFile(file).catch(() => null);
      if (!doc || typeof doc !== "object") {
        setErrors([{ path: "", code: "malformed" }]);
        return;
      }
      const said = await api.post("/api/staff/problems/import/", { body: doc as DocumentBody });
      onImported(said.problem.id);
    } catch (failed) {
      setErrors(failed instanceof ApiError ? failed.errors : [{ path: "", code: "network" }]);
    } finally {
      setBusy(false);
    }
  };
  return { busy, errors, pick };
}

export function ImportButton({ busy, onFile }: { busy: boolean; onFile: (file: File) => void }) {
  return <FilePick label={t("staff.import")} busy={busy} onFile={onFile} />;
}

export function ImportErrors({ errors }: { errors: ShownError[] }) {
  if (!errors.length) return null;
  return (
    <Notice tone="danger" title={t("staff.errors_title", { count: errors.length })}>
      <ErrorList items={errors.map((error) => ({ path: error.path, text: errorLine(error) }))} />
    </Notice>
  );
}
