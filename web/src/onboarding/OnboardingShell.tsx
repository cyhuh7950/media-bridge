import { useCallback, useEffect, useState } from "react";

import { adminRequest } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { AdminStep } from "./AdminStep";
import { ConnectionStep } from "./ConnectionStep";
import { ModelsStep } from "./ModelsStep";
import { PolicyStep } from "./PolicyStep";
import { ProviderStep } from "./ProviderStep";
import { PublishStep } from "./PublishStep";
import { SystemCheckStep } from "./SystemCheckStep";
import { deriveOnboardingStep, type OnboardingInventory } from "./onboardingState";

async function loadInventory(): Promise<OnboardingInventory> {
  const [providers, models, policies, credentials, snapshots] = await Promise.all([
    adminRequest<Array<Record<string, unknown>>>("/providers"),
    adminRequest<Array<Record<string, unknown>>>("/models"),
    adminRequest<Array<Record<string, unknown>>>("/policies"),
    adminRequest<Array<Record<string, unknown>>>("/credentials"),
    adminRequest<Array<Record<string, unknown>>>("/snapshots"),
  ]);
  if (![providers, models, policies, credentials, snapshots].every(Array.isArray)) {
    throw new Error("invalid inventory response");
  }
  return { providers, models, policies, credentials, snapshots };
}

export function OnboardingWorkflow({ csrfToken }: { csrfToken: string }) {
  const [inventory, setInventory] = useState<OnboardingInventory | null>(null);
  const [failed, setFailed] = useState(false);
  const reload = useCallback(async () => {
    try {
      setInventory(await loadInventory());
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, []);
  useEffect(() => {
    let active = true;
    void loadInventory().then(
      (loaded) => {
        if (active) setInventory(loaded);
      },
      () => {
        if (active) setFailed(true);
      },
    );
    return () => {
      active = false;
    };
  }, []);
  if (failed) return <p role="alert">온보딩 상태를 불러올 수 없습니다.</p>;
  if (inventory === null) return <p role="status">온보딩 상태를 확인하고 있습니다.</p>;
  const step = deriveOnboardingStep(inventory);
  if (step === "provider") return <ProviderStep csrfToken={csrfToken} onSaved={reload} />;
  if (step === "model") return <ModelsStep csrfToken={csrfToken} onSaved={reload} />;
  if (step === "policy") return <PolicyStep csrfToken={csrfToken} onSaved={reload} />;
  if (step === "credential") return <ConnectionStep csrfToken={csrfToken} onSaved={reload} />;
  if (step === "publish") return <PublishStep csrfToken={csrfToken} onPublished={reload} />;
  return <section className="setup-card"><h1>온보딩 완료</h1><p>서명 snapshot이 실제로 발행되었습니다.</p><a href="/">Dashboard로 이동</a></section>;
}

export function OnboardingShell() {
  const auth = useAuth();
  const [systemReady, setSystemReady] = useState(false);
  if (auth.status === "loading") return <p role="status">세션을 확인하고 있습니다.</p>;
  if (auth.status === "anonymous") {
    return systemReady ? (
      <AdminStep onComplete={auth.login} />
    ) : (
      <SystemCheckStep onReady={() => { setSystemReady(true); }} />
    );
  }
  if (auth.principal.role !== "admin") return <p role="alert">온보딩은 admin만 수행할 수 있습니다.</p>;
  if (auth.csrfToken === null) {
    return <section className="setup-card"><h1>재인증 필요</h1><p>새 설정을 저장하려면 로그아웃 후 다시 로그인하세요.</p><button type="button" onClick={() => { void auth.logout(); }}>로그아웃</button></section>;
  }
  return <OnboardingWorkflow csrfToken={auth.csrfToken} />;
}
