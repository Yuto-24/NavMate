import type { StartupProgress, StartupStage } from "../startupProgress";

const messages: Record<StartupStage, string> = {
  authentication: "ログイン状態を確認しています",
  runtime: "計算環境を準備しています",
  download: "アプリのデータを取得しています",
  packages: "計算用のパッケージを展開しています",
  application: "計算機能を読み込んでいます",
  projects: "保存済みプロジェクトを確認しています",
  ready: "起動の準備ができました",
};

export function StartupStatus({ progress }: { progress: StartupProgress }) {
  return <>
    <img className="loading-mark" src="/navmate-192.png" width={52} height={52} alt="" />
    <strong>NavMateを起動しています</strong>
    <div className="startup-progress">
      <progress value={progress.percent} max={100} aria-label="起動の進み具合（目安）" />
      <span>{Math.floor(progress.percent)}%</span>
    </div>
    <div role="status" aria-live="polite">{messages[progress.stage]}</div>
  </>;
}
