import { useEffect, useState } from "react";
import { getModels, type ModelInfo } from "./api";
import ChatPanel from "./components/ChatPanel";
import ModelsPopover from "./components/ModelsPopover";
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
    <div className="flex h-screen flex-col">
      <header className="flex items-center justify-between gap-4 border-b border-line px-6 py-4">
        <div>
          <h1 className="font-serif text-[1.55rem] font-medium leading-none tracking-tight text-fg">
            pp<span className="text-accent-strong">·</span>router
          </h1>
          <p className="mt-1.5 font-mono text-[10.5px] lowercase tracking-[0.22em] text-fg-dim">
            llm gateway — routed by difficulty
          </p>
        </div>
        <ModelsPopover models={models} error={modelsError} />
      </header>

      <main className="grid min-h-0 flex-1 grid-cols-1 gap-5 p-5 lg:grid-cols-[1fr_380px] lg:grid-rows-[minmax(0,1fr)] lg:overflow-hidden">
        <ChatPanel
          models={models}
          onChatComplete={() => setHistoryVersion((v) => v + 1)}
        />
        <HistoryPanel version={historyVersion} />
      </main>
    </div>
  );
}
