export interface OnboardingInventory {
  providers: Array<Record<string, unknown>>;
  models: Array<Record<string, unknown>>;
  policies: Array<Record<string, unknown>>;
  credentials: Array<Record<string, unknown>>;
  snapshots: Array<Record<string, unknown>>;
}

export type OnboardingStep =
  | "provider"
  | "model"
  | "policy"
  | "credential"
  | "publish"
  | "complete";

export function deriveOnboardingStep(inventory: OnboardingInventory): OnboardingStep {
  if (inventory.providers.length === 0) return "provider";
  if (inventory.models.length === 0) return "model";
  if (inventory.policies.length === 0) return "policy";
  if (inventory.credentials.length === 0) return "credential";
  if (inventory.snapshots.length === 0) return "publish";
  return "complete";
}
