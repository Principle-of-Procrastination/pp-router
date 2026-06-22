import { useEffect, useState } from "react";
import { getModels, type ModelInfo } from "./api";
import ChatPanel from "./components/ChatPanel";
import ModelsPanel from "./components/ModelsPanel";
import HistoryPanel from "./components/HistoryPanel";

export default function App() {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [historyVersion, setHistoryVersion] = useState(0);

  useEffect(() => {
    getModels()
      .then(setModels)
      .catch((e) => setModelsError(e instanceof Error ? e.message : String(e)));
  }, []);

  return (
    <div className="flex h-screen flex-col bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 px-6 py-3">
        <h1 className="text-base font-semibold">
          pp-router <span className="text-slate-500">控制台</span>
        </h1>
        <p className="text-xs text-slate-500">
          难度自动路由的 LLM 网关 · 模型 / 对话 / 用量
        </p>
      </header>
      <main className="grid min-h-0 flex-1 grid-cols-1 gap-4 p-4 lg:grid-cols-[1fr_380px]">
        <ChatPanel
          models={models}
          onChatComplete={() => setHistoryVersion((v) => v + 1)}
        />
        <aside className="flex min-h-0 flex-col gap-4">
          <ModelsPanel models={models} error={modelsError} />
          <HistoryPanel version={historyVersion} />
        </aside>
      </main>
    </div>
  );
}
