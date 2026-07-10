import { useState, type FormEvent } from "react";
import { KeyRound } from "lucide-react";
import { login } from "../api";

export default function AuthPanel({ onAuthenticated }: { onAuthenticated: () => void }) {
  const [accessKey, setAccessKey] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!accessKey || loading) return;
    setLoading(true);
    setError(null);
    try {
      await login(accessKey);
      setAccessKey("");
      onAuthenticated();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-0 w-full max-w-xl flex-1 items-center px-4 py-8 sm:px-6">
      <section className="w-full border-y border-line py-8 sm:py-10">
        <div className="flex items-center gap-3">
          <KeyRound aria-hidden="true" className="h-5 w-5 text-accent-strong" />
          <h2 className="font-serif text-xl text-fg sm:text-2xl">受保护的路由控制台</h2>
        </div>
        <form className="mt-6 flex flex-col gap-3 sm:flex-row" onSubmit={submit}>
          <label className="min-w-0 flex-1">
            <span className="sr-only">访问密钥</span>
            <input
              type="password"
              autoComplete="current-password"
              value={accessKey}
              onChange={(event) => setAccessKey(event.target.value)}
              placeholder="输入访问密钥"
              className="min-h-11 w-full rounded-md border border-line bg-surface-2 px-3.5 text-sm text-fg outline-none placeholder:text-fg-dim focus:border-accent/50"
            />
          </label>
          <button
            type="submit"
            disabled={!accessKey || loading}
            className="min-h-11 rounded-md bg-accent px-5 text-sm font-medium text-ink hover:bg-accent-strong disabled:cursor-not-allowed disabled:bg-surface-2 disabled:text-fg-dim"
          >
            {loading ? "验证中…" : "进入控制台"}
          </button>
        </form>
        {error && <p className="mt-3 text-sm text-[#e8a89c]">验证失败：{error}</p>}
      </section>
    </main>
  );
}
