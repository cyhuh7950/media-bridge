import { useCallback, useEffect, useState } from "react";

import { adminRequest } from "../api/client";
import { records } from "./operationTypes";

export function useAdminList(path: string | null) {
  const [items, setItems] = useState<Array<Record<string, unknown>> | null>(null);
  const [failed, setFailed] = useState(false);

  const reload = useCallback(async () => {
    if (path === null) {
      setItems([]);
      return;
    }
    try {
      setItems(records(await adminRequest<unknown>(path)));
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [path]);

  useEffect(() => {
    if (path === null) return;
    let active = true;
    void adminRequest<unknown>(path).then(
      (response) => {
        if (active) setItems(records(response));
      },
      () => {
        if (active) setFailed(true);
      },
    );
    return () => {
      active = false;
    };
  }, [path]);

  return { items, failed, reload };
}
