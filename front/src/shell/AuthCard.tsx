import type { ComponentChildren } from "preact";
import { useEffect } from "preact/hooks";
import { useSession } from "../api/hooks";
import { navigate } from "../router";
import { Card, CardTitle, PageBody, Stack, Text } from "../ui";
import { AppPage } from "./AppPage";

export interface AuthCardProps {
  page: string;
  title: string;
  foot: ComponentChildren;
  children: ComponentChildren;
}

export function AuthCard({ page, title, foot, children }: AuthCardProps) {
  return (
    <AppPage title={page} bare>
      <PageBody narrow>
        <Card pad="md">
          <CardTitle>{title}</CardTitle>
          <Stack>
            {children}
            <Text tone="muted" small>{foot}</Text>
          </Stack>
        </Card>
      </PageBody>
    </AppPage>
  );
}

export function useLeaveWhenSignedIn(destination: string): void {
  const { me } = useSession();
  useEffect(() => {
    if (me) navigate(destination, true);
  }, [me, destination]);
}
