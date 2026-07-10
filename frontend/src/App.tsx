import { useCallback, useEffect, useState } from "react";
import { LogOut } from "lucide-react";
import {
  ApiError,
  clearSession,
  getModels,
  hasSession,
  type ModelInfo,
} from "./api";
import AuthPanel from "./components/AuthPanel";
import ChatPanel from "./components/ChatPanel";
import ModelsPopover from "./components/ModelsPopover";
import HistoryPanel from "./components/HistoryPanel";

export default function App() {
  const [authenticated, setAuthenticated] = useState(hasSession);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [historyVersion, setHistoryVersion] = useState(0);

  const handleUnauthorized = useCallback(() => {
    clearSession();
    setAuthenticated(false);
    setModels([]);
    setHistoryVersion(0);
  }, []);

  useEffect(() => {
    if (!authenticated) return;
    setModelsError(null);
    getModels()
      .then(setModels)
      .catch((error) => {
        if (error instanceof ApiError && error.status === 401) {
          handleUnauthorized();
          return;
        }
        setModelsError(error instanceof Error ? error.message : String(error));
      });
  }, [authenticated, handleUnauthorized]);

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
        {authenticated && (
          <div className="flex items-center gap-2">
            <ModelsPopover models={models} error={modelsError} />
            <button
              type="button"
              title="退出控制台"
              aria-label="退出控制台"
              onClick={handleUnauthorized}
              className="grid h-8 w-8 place-items-center rounded-md text-fg-dim hover:bg-surface-2 hover:text-fg"
            >
              <LogOut aria-hidden="true" className="h-4 w-4" />
            </button>
          </div>
        )}
      </header>

      {authenticated ? (
        <main className="mx-auto grid min-h-0 w-full max-w-[1600px] flex-1 grid-cols-1 grid-rows-[minmax(0,1.05fr)_minmax(0,0.95fr)] gap-3 overflow-hidden p-3 sm:gap-5 sm:p-5 lg:grid-cols-[minmax(0,1fr)_380px] lg:grid-rows-[minmax(0,1fr)] xl:grid-cols-[minmax(0,1fr)_400px]">
          <ChatPanel
            models={models}
            onChatComplete={() => setHistoryVersion((v) => v + 1)}
            onUnauthorized={handleUnauthorized}
          />
          <HistoryPanel version={historyVersion} onUnauthorized={handleUnauthorized} />
        </main>
      ) : (
        <AuthPanel onAuthenticated={() => setAuthenticated(true)} />
      )}
    </div>
  );
}
