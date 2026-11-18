import { useSyncExternalStore, type ReactNode } from "react";
import { authenticationProgress, type StartupProgressSource, type StartupStage } from "../startupProgress";

const messages: Record<StartupStage, string> = {
  authentication: "利用環境を確認しています",
  runtime: "計算に必要な環境を準備しています",
  dependencies: "計算に必要な追加部品を読み込んでいます",
  assets: "計算用プログラムとデータを読み込んでいます",
  application: "計算機能を準備しています",
  projects: "保存済みプロジェクトを確認しています",
};
const initialSnapshot = () => authenticationProgress;
const noSubscription = () => () => {};

export function StartupScreen({ source, children, showProgress = true }: {
  source?: StartupProgressSource; children?: ReactNode; showProgress?: boolean;
}) {
  const progress = useSyncExternalStore(source?.subscribe ?? noSubscription, source?.getSnapshot ?? initialSnapshot);
  return <main className="loading-screen">
    <img className="loading-mark" src="/navmate-192.png" width={52} height={52} alt="" />
    <strong>NavMateの起動</strong>
    {showProgress && <>
      <progress className="startup-progress" value={progress.percent} max={100} aria-label="起動の進み具合" aria-describedby="startup-stage" />
      <span id="startup-stage" className="startup-stage" role="status">{messages[progress.stage]}</span>
    </>}
    {children}
  </main>;
}
