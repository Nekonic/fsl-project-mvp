import type { Schemas } from "../../api/client";
import { useResource, useRowAction, useSession } from "../../api/hooks";
import { clock, count, day } from "../../format";
import type { PageProps } from "../../routes";
import { AppPage } from "../../shell/AppPage";
import { errorText, t, tFor, type StringKey } from "../../strings";
import { Badge, Button, Card, CardHead, ErrorNotice, Loading, PageBody, Row, Section, Stack, Table, Text, type BadgeTone, type Column, RowActions, IdentityCell } from "../../ui";

type Account = Schemas["Account"];
type Block = Schemas["Block"];
type Standing = "pending" | "active" | "disabled";

function standingOf(account: Account): Standing {
  return account.approved ? "active" : "pending";
}

interface StandingSection {
  standing: Standing;
  title: StringKey;
  empty: StringKey;
  tone: BadgeTone;
  columns: Array<"account" | "role" | "joined" | "approve" | "disable">;
}

const SECTIONS: StandingSection[] = [
  { standing: "pending", title: "users.pending", empty: "users.pending_none", tone: "warn", columns: ["account", "joined", "approve"] },
  { standing: "active", title: "users.active", empty: "users.active_none", tone: "neutral", columns: ["account", "role", "joined", "disable"] },
  { standing: "disabled", title: "users.disabled", empty: "users.disabled_none", tone: "muted", columns: ["account", "role", "joined"] },
];

function roleBadge(account: Account, muted: boolean) {
  return (
    <Badge tone={muted ? "muted" : account.is_staff ? "info" : "neutral"}>
      {t(account.is_staff ? "users.role.staff" : "users.role.learner")}
    </Badge>
  );
}

function AccountsCard({ section, accounts, onChanged }: { section: StandingSection; accounts: Account[]; onChanged: (account: Account) => void }) {
  const approve = useRowAction<string, "post", "/api/staff/users/{username}/approve/">("post", "/api/staff/users/{username}/approve/");
  const disable = useRowAction<string, "post", "/api/staff/users/{username}/disable/">("post", "/api/staff/users/{username}/disable/");
  const { me } = useSession();
  const muted = section.standing === "disabled";
  const settled = (said: { data?: Account }) => said.data && onChanged(said.data);
  const every: Record<StandingSection["columns"][number], Column<Account>> = {
    account: { key: "account", label: t("users.col.account"), cell: (account) => <IdentityCell name={account.username} /> },
    role: { key: "role", label: t("users.col.role"), cell: (account) => roleBadge(account, muted) },
    joined: { key: "joined", label: t("users.col.joined"), kind: "nowrap", cell: (account) => <Text tone="muted">{day(account.joined)}</Text> },
    approve: {
      key: "approve", label: "", kind: "end",
      cell: (account) => (
        <RowActions error={approve.errorFor(account.username) && errorText(approve.errorFor(account.username))}>
          <Button tone="primary" small busy={approve.busyFor(account.username)}
            onClick={() => void approve.run(account.username, { params: { username: account.username } }).then(settled)}>
            {t("users.approve")}
          </Button>
        </RowActions>
      ),
    },
    disable: {
      key: "disable", label: "", kind: "end",
      cell: (account) => account.username === me?.user ? <Text tone="muted">{t("users.self")}</Text> : (
        <RowActions error={disable.errorFor(account.username) && errorText(disable.errorFor(account.username))}>
          <Button small busy={disable.busyFor(account.username)}
            onClick={() => void disable.run(account.username, { params: { username: account.username } }).then(settled)}>
            {t("users.disable")}
          </Button>
        </RowActions>
      ),
    },
  };
  return (
    <Card>
      <CardHead title={t(section.title)} meta={<Badge tone={section.tone}>{count(accounts.length)}</Badge>} />
      <Table variant="grid" columns={section.columns.map((name) => every[name])} rows={accounts} rowKey={(account) => account.username}
        muted={() => muted} empty={<Text tone="muted">{t(section.empty)}</Text>} />
    </Card>
  );
}

function BlocksCard() {
  const blocks = useResource("/api/staff/blocks/", {});
  const unblock = useRowAction<number, "delete", "/api/staff/blocks/{block_id}/">("delete", "/api/staff/blocks/{block_id}/");
  const lift = async (block: Block) => {
    const said = await unblock.run(block.id, { params: { block_id: block.id } });
    if (said.ok && blocks.data) blocks.setData(blocks.data.filter((one) => one.id !== block.id));
  };
  const columns: Column<Block>[] = [
    {
      key: "what", label: t("users.col.blocked"), kind: "nowrap",
      cell: (block) => (
        <Row>
          <Badge tone="danger">{tFor("users.block", block.kind)}</Badge>
          <Text mono tone="heading" cut title={block.value}>{block.value}</Text>
        </Row>
      ),
    },
    { key: "username", label: t("users.col.target"), cell: (block) => block.username },
    { key: "failures", label: t("users.col.failures"), kind: "num", cell: (block) => count(block.failures) },
    { key: "until", label: t("users.col.until"), kind: "mono", cell: (block) => <Text tone="muted">{clock(block.until)}</Text> },
    {
      key: "unblock", label: "", kind: "end",
      cell: (block) => (
        <RowActions error={unblock.errorFor(block.id) && errorText(unblock.errorFor(block.id))}>
          <Button small busy={unblock.busyFor(block.id)} onClick={() => void lift(block)}>{t("users.unblock")}</Button>
        </RowActions>
      ),
    },
  ];
  return (
    <Card>
      <CardHead title={t("users.blocks")} meta={blocks.data && <Badge tone="danger">{count(blocks.data.length)}</Badge>} />
      {blocks.error ? <ErrorNotice error={blocks.error} /> : !blocks.data ? <Loading>{t("common.loading")}</Loading> : (
        <Table variant="grid" columns={columns} rows={blocks.data} rowKey={(block) => block.id}
          empty={<Text tone="muted">{t("users.blocks_none")}</Text>} />
      )}
    </Card>
  );
}

export function Users(_props: PageProps) {
  const users = useResource("/api/staff/users/", {});
  const changed = (account: Account) => users.data && users.setData(users.data.map((one) => (one.username === account.username ? account : one)));
  const of = (standing: Standing) => (users.data ?? []).filter((account) => standingOf(account) === standing);
  const shown = SECTIONS.filter((section) => section.standing !== "disabled" || of("disabled").length > 0);
  return (
    <AppPage title={t("page.staff.users")} crumbs={[{ label: t("page.staff.users") }]}>
      <PageBody>
        <Section title={t("users.title")} large>
          {users.error ? <ErrorNotice error={users.error} /> : !users.data ? <Loading>{t("common.loading")}</Loading> : (
            <Stack>
              {shown.map((section) => <AccountsCard key={section.standing} section={section} accounts={of(section.standing)} onChanged={changed} />)}
              <BlocksCard />
            </Stack>
          )}
        </Section>
      </PageBody>
    </AppPage>
  );
}
