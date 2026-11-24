import type { Schemas } from "../api/client";
import { useAction, useResource, useSession } from "../api/hooks";
import type { PageProps } from "../routes";
import { AppPage } from "../shell/AppPage";
import { t } from "../strings";
import { Button, Card, CardHead, Code, ErrorNotice, KeyValue, Loading, Notice, PageBody, Section, Stack, Text } from "../ui";

type Ssh = Schemas["Ssh"];
type RoundLine = Schemas["RoundLine"];

export const KEY_FILE = "~/.ssh/cr-round";
const JUMP_ALIAS = "range-jump";
const BOX_ALIAS = "range-box";
const SOCKS_PORT = 1080;

export function sshConfig(ssh: Ssh): string {
  return [
    `Host ${JUMP_ALIAS}`,
    `  HostName ${ssh.host}`,
    `  Port ${ssh.port}`,
    `  User ${ssh.user}`,
    `  IdentityFile ${KEY_FILE}`,
    "  IdentitiesOnly yes",
    "",
    `Host ${BOX_ALIAS}`,
    `  HostName ${ssh.target_host}`,
    `  User ${ssh.target_user}`,
    `  ProxyJump ${JUMP_ALIAS}`,
    `  IdentityFile ${KEY_FILE}`,
    "  IdentitiesOnly yes",
    `  DynamicForward ${SOCKS_PORT}`,
    "",
  ].join("\n");
}

function attackRound(lines: RoundLine[] | undefined, user: string | undefined): number | null {
  const playing = (lines ?? []).find((line) => line.phase === "running"
    && line.players.some((player) => player.side === "attack" && player.client === "human" && player.username === user));
  return playing ? playing.round : null;
}

function Profile() {
  const shown = useResource("/api/vpn/profile/", {});
  const issue = useAction("post", "/api/vpn/profile/");
  const revoke = useAction("delete", "/api/vpn/profile/");
  const missing = shown.error?.status === 404;
  const issued = issue.data;
  const held = issued ?? shown.data;

  const reissue = async () => {
    if (await issue.run()) shown.reload();
  };
  const drop = async () => {
    await revoke.run();
    issue.reset();
    shown.reload();
  };

  return (
    <Card pad="md">
      <CardHead title={t("access.vpn.title")} actions={<>
        <Button tone="primary" small busy={issue.busy} onClick={() => void reissue()}>
          {t(held ? "access.vpn.reissue" : "access.vpn.issue")}
        </Button>
        {held && <Button tone="ghost" small busy={revoke.busy} onClick={() => void drop()}>{t("access.vpn.revoke")}</Button>}
      </>} />
      <Stack>
        <Text tone="muted">{t("access.vpn.lead")}</Text>
        {issue.error && <ErrorNotice error={issue.error} />}
        {revoke.error && <ErrorNotice error={revoke.error} />}
        {shown.error && !missing && <ErrorNotice error={shown.error} />}
        {shown.loading && !held && <Loading>{t("common.loading")}</Loading>}
        {missing && !issued && <Text>{t("access.vpn.none")}</Text>}
        {issued && <>
          <Notice tone="warn">{t("access.vpn.once")}</Notice>
          <Code>{issued.profile}</Code>
        </>}
        {held && <KeyValue items={[
          [t("access.vpn.address"), <Text mono>{held.address}</Text>],
          [t("access.vpn.endpoint"), <Text mono>{held.endpoint}</Text>],
          [t("access.vpn.attached"), held.attached_round ? t("round.name", { round: held.attached_round }) : t("access.vpn.detached")],
        ]} />}
        {held && held.hosts.length > 0 && <>
          <Text>{t("access.vpn.hosts")}</Text>
          <Code>{held.hosts.join("\n")}</Code>
        </>}
      </Stack>
    </Card>
  );
}

function SshSnippet({ round }: { round: number }) {
  const grant = useResource("/api/rounds/{round_id}/attack/terminal/", { params: { round_id: round } });
  return (
    <Card pad="md">
      <CardHead title={t("access.ssh.title")} meta={t("round.name", { round })} />
      <Stack>
        {grant.error && <ErrorNotice error={grant.error} />}
        {!grant.data && !grant.error && <Loading>{t("common.loading")}</Loading>}
        {grant.data && <>
          <Text>{t("access.ssh.key", { file: KEY_FILE })}</Text>
          <Code>{grant.data.ssh.private_key}</Code>
          <Text>{t("access.ssh.config")}</Text>
          <Code>{sshConfig(grant.data.ssh)}</Code>
          <Text tone="muted">{t("access.ssh.use", { alias: BOX_ALIAS, port: SOCKS_PORT })}</Text>
        </>}
      </Stack>
    </Card>
  );
}

export function Access(_props: PageProps) {
  const session = useSession();
  const mine = useResource("/api/rounds/", { query: { mine: true } });
  const round = attackRound(mine.data, session.me?.user);
  return (
    <AppPage title={t("page.access")} crumbs={[{ label: t("page.access") }]}>
      <PageBody>
        <Section title={t("page.access")} sub={t("access.lead")}>
          <Stack>
            <Profile />
            {round
              ? <SshSnippet round={round} />
              : <Card pad="md"><CardHead title={t("access.ssh.title")} /><Text tone="muted">{t("access.ssh.none")}</Text></Card>}
          </Stack>
        </Section>
      </PageBody>
    </AppPage>
  );
}
