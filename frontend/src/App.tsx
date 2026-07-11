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
    setModelsError(null);
    getModels()
      .then(setModels)
      .catch((error) => {
        setModelsError(error instanceof Error ? error.message : String(error));
      });
  }, []);

  return (
    <div className="flex h-dvh flex-col overflow-hidden pb-[env(safe-area-inset-bottom)]">
      <header className="flex shrink-0 items-center justify-between gap-3 border-b border-line px-4 py-3 sm:gap-4 sm:px-6 sm:py-4">
        <div>
          <h1 className="font-serif text-[1.35rem] font-medium leading-none tracking-tight text-fg sm:text-[1.55rem]">
            pp<span className="text-accent-strong">·</span>router
          </h1>
          <p className="mt-1 font-mono text-[10px] lowercase tracking-[0.22em] text-fg-dim sm:mt-1.5 sm:text-[10.5px]">
            llm gateway — routed by difficulty
          </p>
        </div>
        <ModelsPopover models={models} error={modelsError} />
      </header>

      <main className="mx-auto grid min-h-0 w-full max-w-[1600px] flex-1 grid-cols-1 grid-rows-[minmax(0,1.05fr)_minmax(0,0.95fr)] gap-3 overflow-hidden p-3 sm:gap-5 sm:p-5 lg:grid-cols-[minmax(0,1fr)_380px] lg:grid-rows-[minmax(0,1fr)] xl:grid-cols-[minmax(0,1fr)_400px]">
        <ChatPanel
          models={models}
          onChatComplete={() => setHistoryVersion((v) => v + 1)}
        />
        <HistoryPanel version={historyVersion} />
      </main>
    </div>
  );
}
