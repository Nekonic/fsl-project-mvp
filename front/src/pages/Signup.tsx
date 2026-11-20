import { useState } from "preact/hooks";
import { useAction } from "../api/hooks";
import { to } from "../links";
import type { PageProps } from "../routes";
import { fieldErrors, formErrors, t } from "../strings";
import { Button, Field, Form, FormErrorLines, Input, Prose } from "../ui";
import { AuthCard, useLeaveWhenSignedIn } from "../shell/AuthCard";

const SIGN_UP_FIELDS = ["username", "password"];

export function Signup(_props: PageProps) {
  const signUp = useAction("post", "/api/auth/signup/");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  useLeaveWhenSignedIn(to.home());

  const byField = fieldErrors(signUp.error);
  return (
    <AuthCard page={t("page.signup")} title={t("signup.title")} foot={<Button tone="link" href={to.login()}>{t("signup.to_login")}</Button>}>
      {signUp.data
        ? <Prose>{t("signup.pending")}</Prose>
        : (
          <Form onSubmit={() => void signUp.run({ body: { username, password } })}>
            <Field label={t("auth.username")} error={byField.username}>
              <Input value={username} onValue={setUsername} name="username" autoFocus autoComplete="username" autoCapitalize="off"
                spellcheck={false} required bad={Boolean(byField.username)} />
            </Field>
            <Field label={t("auth.password")} hint={t("signup.password_rule")} error={byField.password}>
              <Input value={password} onValue={setPassword} name="password" type="password" autoComplete="new-password" required
                bad={Boolean(byField.password)} />
            </Field>
            <FormErrorLines lines={formErrors(signUp.error, SIGN_UP_FIELDS)} />
            <Button tone="primary" type="submit" block busy={signUp.busy}>{t("signup.submit")}</Button>
          </Form>
        )}
    </AuthCard>
  );
}
