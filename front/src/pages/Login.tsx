import { useState } from "preact/hooks";
import { useAction, useSession } from "../api/hooks";
import { to } from "../links";
import type { PageProps } from "../routes";
import { usePlace } from "../router";
import { AuthCard, useLeaveWhenSignedIn } from "../shell/AuthCard";
import { fieldErrors, formErrors, t } from "../strings";
import { Button, Field, Form, FormErrorLines, Input } from "../ui";

const CREDENTIAL_FIELDS = ["username", "password"];

function safeNext(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/login") ? next : to.home();
}

export function Login(_props: PageProps) {
  const place = usePlace();
  const session = useSession();
  const signIn = useAction("post", "/api/auth/login/");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  useLeaveWhenSignedIn(safeNext(place.search.get("next")));

  const submit = async () => {
    const signedIn = await signIn.run({ body: { username, password } });
    if (signedIn) session.reload();
  };

  const byField = fieldErrors(signIn.error);
  const signUpLink = <Button tone="link" href={to.signup()}>{t("auth.sign_up")}</Button>;
  return (
    <AuthCard page={t("page.login")} title={t("auth.title")} foot={<>{t("auth.no_account")} {signUpLink}</>}>
      <Form onSubmit={() => void submit()}>
        <Field label={t("auth.username")} error={byField.username}>
          <Input value={username} onValue={setUsername} name="username" autoFocus autoComplete="username" autoCapitalize="off"
            spellcheck={false} required bad={Boolean(byField.username)} />
        </Field>
        <Field label={t("auth.password")} error={byField.password}>
          <Input value={password} onValue={setPassword} name="password" type="password" autoComplete="current-password" required
            bad={Boolean(byField.password)} />
        </Field>
        <FormErrorLines lines={formErrors(signIn.error, CREDENTIAL_FIELDS)} />
        <Button tone="primary" type="submit" block busy={signIn.busy}>{t("auth.submit")}</Button>
      </Form>
    </AuthCard>
  );
}
