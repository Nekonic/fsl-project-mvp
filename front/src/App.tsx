import { useEffect, useMemo, useState } from "preact/hooks";
import { api, onSignedOut, type Schemas } from "./api/client";
import { SessionContext, type Session } from "./api/hooks";
import { to } from "./links";
import { resolve } from "./routes";
import { navigate, usePlace } from "./router";

function useMe(): Session {
  const [me, setMe] = useState<Schemas["Me"] | undefined>(undefined);
  const [loading, setLoading] = useState(true);
  const [asked, setAsked] = useState(0);
  useEffect(() => {
    let current = true;
    setLoading(true);
    api.get("/api/me/")
      .then((said) => current && setMe(said))
      .catch(() => current && setMe(undefined))
      .finally(() => current && setLoading(false));
    return () => {
      current = false;
    };
  }, [asked]);
  useEffect(() => onSignedOut(() => setMe(undefined)), []);
  return useMemo(() => ({ me, loading, reload: () => setAsked((was) => was + 1) }), [me, loading]);
}

export function App() {
  const place = usePlace();
  const session = useMe();
  const found = resolve(place.path);

  const access = found?.route.access ?? "member";
  const refused = !session.loading && access !== "public" && (!session.me || (access === "staff" && !session.me.is_staff));
  useEffect(() => {
    if (!found) navigate(to.home(), true);
    else if (refused) navigate(session.me ? to.home() : to.login(location.pathname + location.search + location.hash), true);
  }, [found, refused]);

  if (!found || refused || (session.loading && access !== "public")) return null;
  const Page = found.route.page;
  return (
    <SessionContext.Provider value={session}>
      <Page params={found.params} />
    </SessionContext.Provider>
  );
}
