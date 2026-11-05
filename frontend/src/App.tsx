import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  Activity,
  ArrowUpRight,
  Building2,
  ChevronRight,
  CircuitBoard,
  Download,
  KeyRound,
  LogOut,
  Plus,
  RefreshCw,
  Send,
  ShieldCheck,
  SlidersHorizontal,
  X,
} from "lucide-react";
import { api, debugCall, formatNumber as num, setCSRF } from "./api";

type Row = Record<string, any>;
const modelIds = ["deepseek-flash", "deepseek-v4-pro", "kimi-k3.1-pro"];
const pageNames = ["总览与月报", "公司与接入", "模型与路由", "调用与调试"];
const icons = [Activity, Building2, CircuitBoard, SlidersHorizontal];
const stamp = (n: number) =>
  new Date(n * 1000).toLocaleString("zh-CN", {
    timeZone: "Asia/Shanghai",
    hour12: false,
  });
function Badge({ on = true, children }: { on?: boolean; children: ReactNode }) {
  return <span className={"badge " + (on ? "good" : "muted")}>{children}</span>;
}
function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}
function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="empty">
      <CircuitBoard size={28} />
      <p>{children}</p>
    </div>
  );
}
function Form({
  onSubmit,
  children,
  title,
}: {
  onSubmit: (data: FormData) => Promise<void>;
  children: ReactNode;
  title: string;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    setBusy(true);
    setError("");
    try {
      await onSubmit(new FormData(form));
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={submit} className="form">
      <h3>{title}</h3>
      {children}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <button className="primary" disabled={busy}>
        {busy ? "处理中…" : "保存"}
        <ArrowUpRight size={15} />
      </button>
    </form>
  );
}

export default function App() {
  const [session, setSession] = useState<Row | null | undefined>(undefined);
  const [page, setPage] = useState(0);
  const [revision, setRevision] = useState(0);
  const [companies, setCompanies] = useState<Row[]>([]),
    [apps, setApps] = useState<Row[]>([]),
    [grants, setGrants] = useState<Row[]>([]),
    [keys, setKeys] = useState<Row[]>([]),
    [models, setModels] = useState<Row[]>([]);
  const [error, setError] = useState(""),
    [secret, setSecret] = useState(""),
    [modal, setModal] = useState<ReactNode>(null);
  async function refresh() {
    const [c, a, g, k, m] = await Promise.all([
      api("/companies"),
      api("/applications"),
      api("/grants"),
      api("/keys"),
      api("/models"),
    ]);
    setCompanies(c);
    setApps(a);
    setGrants(g);
    setKeys(k);
    setModels(m);
    setRevision((n) => n + 1);
  }
  useEffect(() => {
    api("/auth/me")
      .then((s) => {
        setSession(s);
        setCSRF(s.csrf_token);
      })
      .catch(() => setSession(null));
  }, []);
  useEffect(() => {
    if (!session) return;
    Promise.all([
      api("/companies"),
      api("/applications"),
      api("/grants"),
      api("/keys"),
      api("/models"),
    ])
      .then(([c, a, g, k, m]) => {
        setCompanies(c);
        setApps(a);
        setGrants(g);
        setKeys(k);
        setModels(m);
      })
      .catch((e) => setError(e.message));
  }, [session]);
  async function action(fn: () => Promise<unknown>) {
    setError("");
    try {
      await fn();
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  const companyName = (id: string) =>
    companies.find((c) => c.id === id)?.name || id;
  const appName = (id: string) => apps.find((a) => a.id === id)?.name || id;
  const grantName = (id: string) => {
    const g = grants.find((g) => g.id === id);
    return g
      ? `${companyName(g.company_id)} / ${appName(g.application_id)}`
      : "内部开户";
  };
  if (session === undefined)
    return <div className="loading">正在连接本地网关…</div>;
  if (!session)
    return (
      <main className="login">
        <div className="brand-mark">
          pp<span> / </span>router
        </div>
        <p className="eyebrow">ADMIN CONSOLE</p>
        <h1>
          每次调用，
          <br />
          都有来处。
        </h1>
        <p className="muted">
          登录管理端，管理公司接入、模型路由与 token 用量。
        </p>
        <Form
          title="管理员登录"
          onSubmit={async (data) => {
            const s = await api(
              "/auth/login",
              "POST",
              Object.fromEntries(data),
            );
            setSession(s);
            setCSRF(s.csrf_token);
          }}
        >
          <Field label="用户名">
            <input
              name="username"
              defaultValue="pp_admin"
              autoComplete="username"
              required
            />
          </Field>
          <Field label="密码">
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              required
            />
          </Field>
        </Form>
        <small>请使用管理员提供的账号和密码登录。</small>
      </main>
    );
  return (
    <div className="shell">
      <aside>
        <a
          className="brand-mark"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setPage(0);
          }}
        >
          pp<span> / </span>router
        </a>
        <p className="eyebrow">WORKSPACE / ADMIN</p>
        <nav>
          {pageNames.map((name, i) => {
            const Icon = icons[i];
            return (
              <button
                key={name}
                onClick={() => setPage(i)}
                className={page === i ? "active" : ""}
              >
                <Icon size={18} />
                {name}
                {page === i && <ChevronRight size={14} />}
              </button>
            );
          })}
        </nav>
        <div className="sidebar-foot">
          <span className="live-dot" />
          用量时区 · Asia/Shanghai
          <div className="user">
            <ShieldCheck size={18} />
            <span>
              {session.username}
              <small>平台管理员</small>
            </span>
            <button
              aria-label="退出登录"
              onClick={() =>
                action(async () => {
                  await api("/auth/logout", "POST");
                  setSession(null);
                })
              }
            >
              <LogOut size={16} />
            </button>
          </div>
        </div>
      </aside>
      <main className="content">
        <header>
          <div>
            <p className="eyebrow">PP ROUTER / ADMINISTRATION</p>
            <h1>{pageNames[page]}</h1>
          </div>
          <button className="secondary" onClick={() => action(async () => {})}>
            <RefreshCw size={15} />
            刷新
          </button>
        </header>
        {error && (
          <div className="error" role="alert">
            {error}
            <button aria-label="关闭错误" onClick={() => setError("")}>
              <X size={15} />
            </button>
          </div>
        )}
        {page === 0 && (
          <Overview
            companies={companies}
            apps={apps}
            keys={keys}
            revision={revision}
          />
        )}
        {page === 1 && (
          <>
            <div className="section-heading">
              <p>共享应用目录，为每家公司发放独立凭证。</p>
              <div className="inline">
                <button
                  className="secondary"
                  onClick={() =>
                    setModal(
                      <Form
                        title="新增应用"
                        onSubmit={async (f) => {
                          await api(
                            "/applications",
                            "POST",
                            Object.fromEntries(f),
                          );
                          await refresh();
                          setModal(null);
                        }}
                      >
                        <Field label="应用代码">
                          <input
                            name="code"
                            required
                            pattern="[A-Za-z0-9_-]+"
                          />
                        </Field>
                        <Field label="应用名称">
                          <input name="name" required />
                        </Field>
                        <Field label="应用说明">
                          <textarea name="description" />
                        </Field>
                      </Form>,
                    )
                  }
                >
                  <Plus size={15} />
                  新增应用
                </button>
                <button
                  className="primary"
                  onClick={() =>
                    setModal(
                      <Form
                        title="公司开户"
                        onSubmit={async (f) => {
                          const v = Object.fromEntries(f);
                          if (!v.external_id) delete v.external_id;
                          await api("/companies", "POST", v);
                          await refresh();
                          setModal(null);
                        }}
                      >
                        <Field label="公司代码">
                          <input
                            name="code"
                            required
                            pattern="[A-Za-z0-9_-]+"
                          />
                        </Field>
                        <Field label="公司名称">
                          <input name="name" required />
                        </Field>
                        <Field label="套件侧公司 ID（可选）">
                          <input name="external_id" />
                        </Field>
                      </Form>,
                    )
                  }
                >
                  <Plus size={15} />
                  公司开户
                </button>
              </div>
            </div>
            <section className="panel">
              <div className="panel-heading">
                <h2>公司目录</h2>
                <span>{companies.length} 家公司</span>
              </div>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>公司</th>
                      <th>套件侧 ID</th>
                      <th>授权应用</th>
                      <th>状态</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {companies.map((c) => (
                      <tr key={c.id}>
                        <td>
                          <strong>{c.name}</strong>
                          <small>{c.code}</small>
                        </td>
                        <td>{c.external_id || "—"}</td>
                        <td>
                          {
                            grants.filter(
                              (g) => g.company_id === c.id && g.enabled,
                            ).length
                          }
                        </td>
                        <td>
                          <Badge on={c.enabled}>
                            {c.enabled ? "已启用" : "已停用"}
                          </Badge>
                        </td>
                        <td className="inline">
                          <button
                            onClick={() =>
                              action(() =>
                                api("/companies/" + c.id, "PATCH", {
                                  enabled: !c.enabled,
                                }),
                              )
                            }
                          >
                            {c.enabled ? "停用" : "启用"}
                          </button>
                          <button
                            onClick={() =>
                              setModal(
                                <Form
                                  title={`为 ${c.name} 开通应用`}
                                  onSubmit={async (f) => {
                                    await api("/grants", "POST", {
                                      company_id: c.id,
                                      application_id: f.get("application_id"),
                                    });
                                    await refresh();
                                    setModal(null);
                                  }}
                                >
                                  <Field label="选择应用">
                                    <select name="application_id">
                                      {apps.map((a) => (
                                        <option value={a.id} key={a.id}>
                                          {a.name}
                                        </option>
                                      ))}
                                    </select>
                                  </Field>
                                </Form>,
                              )
                            }
                          >
                            开通应用
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
            <div className="two-columns">
              <section className="panel">
                <div className="panel-heading">
                  <h2>应用目录</h2>
                  <span>{apps.length} 个应用</span>
                </div>
                {apps.map((a) => (
                  <div className="list-row" key={a.id}>
                    <div>
                      <strong>{a.name}</strong>
                      <small>
                        {a.code} · {a.description}
                      </small>
                    </div>
                    <button
                      onClick={() =>
                        action(() =>
                          api("/applications/" + a.id, "PATCH", {
                            enabled: !a.enabled,
                          }),
                        )
                      }
                    >
                      {a.enabled ? "停用" : "启用"}
                    </button>
                  </div>
                ))}
              </section>
              <section className="panel">
                <div className="panel-heading">
                  <h2>应用授权与限制</h2>
                </div>
                {grants.map((g) => (
                  <div className="list-row" key={g.id}>
                    <div>
                      <strong>{grantName(g.id)}</strong>
                      <small>
                        {g.enabled
                          ? `${g.rpm} RPM · ${g.concurrency} 并发 · ${g.max_output_tokens} 输出上限`
                          : "已停用"}
                      </small>
                    </div>
                    <button
                      onClick={() =>
                        setModal(
                          <GrantEditor
                            grant={g}
                            title={grantName(g.id)}
                            done={async () => {
                              await refresh();
                              setModal(null);
                            }}
                          />,
                        )
                      }
                    >
                      配置
                    </button>
                  </div>
                ))}
              </section>
            </div>
            <section className="panel">
              <div className="panel-heading">
                <div>
                  <h2>调用与开户凭证</h2>
                  <small>密钥仅在创建时显示一次；撤销后立即停止新调用。</small>
                </div>
                <button
                  className="secondary"
                  onClick={() =>
                    setModal(
                      <Form
                        title="签发凭证"
                        onSubmit={async (f) => {
                          const payload: Row = Object.fromEntries(f);
                          if (!payload.grant_id) payload.grant_id = null;
                          payload.expires_at = payload.expires_at
                            ? new Date(payload.expires_at).getTime() / 1000
                            : null;
                          const k = await api("/keys", "POST", payload);
                          await refresh();
                          setModal(null);
                          setSecret(k.secret);
                        }}
                      >
                        <Field label="绑定应用">
                          <select name="grant_id">
                            <option value="">内部开户凭证</option>
                            {grants.map((g) => (
                              <option key={g.id} value={g.id}>
                                {grantName(g.id)}
                              </option>
                            ))}
                          </select>
                        </Field>
                        <Field label="凭证名称">
                          <input name="name" required />
                        </Field>
                        <Field label="环境">
                          <input
                            name="environment"
                            defaultValue="local"
                            required
                          />
                        </Field>
                        <Field label="过期时间（可选）">
                          <input name="expires_at" type="datetime-local" />
                        </Field>
                      </Form>,
                    )
                  }
                >
                  <KeyRound size={15} />
                  签发凭证
                </button>
              </div>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>凭证</th>
                      <th>归属</th>
                      <th>环境</th>
                      <th>有效期</th>
                      <th>状态</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {keys.map((k) => (
                      <tr key={k.id}>
                        <td>
                          {k.name}
                          <small className="mono">{k.prefix}…</small>
                        </td>
                        <td>{grantName(k.grant_id)}</td>
                        <td>{k.environment}</td>
                        <td>{k.expires_at ? stamp(k.expires_at) : "长期"}</td>
                        <td>
                          <Badge
                            on={
                              k.enabled &&
                              (!k.expires_at ||
                                k.expires_at > Date.now() / 1000)
                            }
                          >
                            {!k.enabled
                              ? "已撤销"
                              : k.expires_at && k.expires_at < Date.now() / 1000
                                ? "已过期"
                                : "有效"}
                          </Badge>
                        </td>
                        <td>
                          {k.enabled && (
                            <div className="inline">
                              <button
                                onClick={() =>
                                  action(async () => {
                                    const row = await api(
                                      `/keys/${k.id}/rotate`,
                                      "POST",
                                    );
                                    setSecret(row.secret);
                                  })
                                }
                              >
                                轮换
                              </button>
                              <button
                                onClick={() =>
                                  action(() =>
                                    api(`/keys/${k.id}/revoke`, "POST"),
                                  )
                                }
                              >
                                撤销
                              </button>
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </>
        )}
        {page === 2 && (
          <>
            <p className="intro">
              只有已配置凭证、已启用且满足应用权限和能力要求的模型，才会进入候选集。
            </p>
            <div className="model-grid">
              {models.map((m) => (
                <section className="panel model-card" key={m.id}>
                  <div className="inline">
                    <span className="provider-icon">
                      {m.provider === "kimi" ? "K" : "D"}
                    </span>
                    <Badge on={m.configured}>
                      {m.configured ? "凭证已配置" : "未配置"}
                    </Badge>
                  </div>
                  <h2 className="mono">{m.id}</h2>
                  <p>
                    {m.provider === "kimi"
                      ? "Kimi 官方 API"
                      : "DeepSeek 官方 API"}
                  </p>
                  <div className="chips">
                    <Badge>文本</Badge>
                    {m.vision && <Badge>图片</Badge>}
                    {m.tools && <Badge>工具</Badge>}
                    {m.formats.map((f: string) => (
                      <Badge key={f}>{f}</Badge>
                    ))}
                  </div>
                  <small>
                    上下文上限 {num(m.context_tokens)} · 输出{" "}
                    {num(m.max_output_tokens)}
                  </small>
                  <button
                    className="secondary"
                    onClick={() =>
                      action(() =>
                        api("/models/" + m.id, "PATCH", {
                          enabled: !m.enabled,
                        }),
                      )
                    }
                  >
                    {m.enabled ? "停用模型" : "启用模型"}
                  </button>
                </section>
              ))}
            </div>
            <section className="panel">
              <div className="panel-heading">
                <h2>应用路由策略</h2>
                <span>能力过滤 → 语义选路 → 受控降级</span>
              </div>
              {grants.map((g) => (
                <div className="list-row" key={g.id}>
                  <div>
                    <strong>{grantName(g.id)}</strong>
                    <small>
                      默认 {g.policy.default_model} · 分类{" "}
                      {g.policy.classifier_model} · v{g.policy_version}
                    </small>
                  </div>
                  <button
                    onClick={() =>
                      setModal(
                        <GrantEditor
                          grant={g}
                          title={grantName(g.id)}
                          done={async () => {
                            await refresh();
                            setModal(null);
                          }}
                        />,
                      )
                    }
                  >
                    编辑策略
                  </button>
                </div>
              ))}
            </section>
            <p className="hint">
              供应商凭证由本地环境变量配置，修改后需重启后端。管理端不会显示或保存上游
              API Key。
            </p>
          </>
        )}
        {page === 3 && (
          <Calls
            revision={revision}
            keys={keys.filter((k) => k.kind === "application" && k.enabled)}
            grantName={grantName}
            companies={companies}
            apps={apps}
          />
        )}
        <footer>
          pp-router <span>管理端 · 仅统计确认 token 用量</span>
        </footer>
      </main>
      {(modal || secret) && (
        <div
          className="modal-backdrop"
          onClick={() => {
            setModal(null);
            setSecret("");
          }}
        >
          <div
            className="modal"
            role="dialog"
            aria-modal="true"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="close"
              aria-label="关闭窗口"
              onClick={() => {
                setModal(null);
                setSecret("");
              }}
            >
              <X size={20} />
            </button>
            {secret ? (
              <>
                <KeyRound size={28} />
                <h2>保存这把密钥</h2>
                <p>关闭后无法再次查看。请交给对应应用的服务端保管。</p>
                <code className="secret">{secret}</code>
                <button
                  className="primary"
                  onClick={() =>
                    navigator.clipboard
                      .writeText(secret)
                      .catch(() => setError("请手动选择并复制密钥。"))
                  }
                >
                  复制密钥
                </button>
              </>
            ) : (
              modal
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function GrantEditor({
  grant,
  title,
  done,
}: {
  grant: Row;
  title: string;
  done: () => void;
}) {
  return (
    <Form
      title={title}
      onSubmit={async (f) => {
        const data = {
          enabled: f.get("enabled") === "on",
          allowed_models: f.getAll("allowed_models"),
          rpm: Number(f.get("rpm")),
          concurrency: Number(f.get("concurrency")),
          max_output_tokens: Number(f.get("max_output_tokens")),
          policy: JSON.parse(String(f.get("policy"))),
        };
        await api("/grants/" + grant.id, "PUT", data);
        done();
      }}
    >
      <label className="check">
        <input type="checkbox" name="enabled" defaultChecked={grant.enabled} />
        启用授权
      </label>
      <div className="field">
        <span>允许使用的模型</span>
        {modelIds.map((m) => (
          <label className="check" key={m}>
            <input
              type="checkbox"
              name="allowed_models"
              value={m}
              defaultChecked={grant.allowed_models.includes(m)}
            />
            {m}
          </label>
        ))}
      </div>
      <div className="inline">
        <Field label="每分钟请求数">
          <input
            type="number"
            name="rpm"
            min="1"
            max="10000"
            defaultValue={grant.rpm}
            required
          />
        </Field>
        <Field label="并发上限">
          <input
            type="number"
            name="concurrency"
            min="1"
            max="128"
            defaultValue={grant.concurrency}
            required
          />
        </Field>
      </div>
      <Field label="输出 token 上限">
        <input
          type="number"
          name="max_output_tokens"
          min="256"
          max="32768"
          defaultValue={grant.max_output_tokens}
          required
        />
      </Field>
      <Field label="路由策略 JSON">
        <textarea
          className="mono"
          rows={12}
          name="policy"
          defaultValue={JSON.stringify(grant.policy, null, 2)}
          required
        />
      </Field>
    </Form>
  );
}

function Overview({
  companies,
  apps,
  keys,
  revision,
}: {
  companies: Row[];
  apps: Row[];
  keys: Row[];
  revision: number;
}) {
  const [filters, setFilters] = useState<Row>({
    month: new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Shanghai",
      year: "numeric",
      month: "2-digit",
    }).format(new Date()),
  });
  const [data, setData] = useState<Row | null>(null),
    [error, setError] = useState("");
  const query = new URLSearchParams(
    Object.entries(filters).filter(([, v]) => v) as [string, string][],
  ).toString();
  useEffect(() => {
    let active = true;
    api("/reports/monthly?" + query)
      .then((d) => {
        if (active) {
          setData(d);
          setError("");
        }
      })
      .catch((e) => active && setError(e.message));
    return () => {
      active = false;
    };
  }, [query, revision]);
  const filter = (name: string, value: string) =>
    setFilters((f) => ({ ...f, [name]: value }));
  const s = data?.summary || {};
  const routeTokens =
    data?.rows
      .filter((r: Row) => r.phase === "routing")
      .reduce((n: number, r: Row) => n + (r.total_tokens || 0), 0) || 0;
  return (
    <>
      <div className="section-heading">
        <p>按公司、应用与实际模型，核对每一次消耗。</p>
        <a
          className="secondary"
          href={"/api/admin/v1/reports/monthly.csv?" + query}
        >
          <Download size={15} />
          导出 CSV
        </a>
      </div>
      <div className="filters">
        <Field label="归属月份">
          <input
            type="month"
            aria-label="归属月份"
            value={filters.month}
            onChange={(e) => filter("month", e.target.value)}
          />
        </Field>
        {[
          ["company_id", "公司", companies],
          ["application_id", "应用", apps],
          ["key_id", "密钥", keys],
        ].map(([name, label, options]) => (
          <Field key={String(name)} label={String(label)}>
            <select onChange={(e) => filter(String(name), e.target.value)}>
              <option value="">全部{String(label)}</option>
              {(options as Row[]).map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
          </Field>
        ))}
        <Field label="环境">
          <input
            placeholder="全部环境"
            onChange={(e) => filter("environment", e.target.value)}
          />
        </Field>
        <Field label="供应商">
          <select onChange={(e) => filter("provider", e.target.value)}>
            <option value="">全部供应商</option>
            <option value="deepseek">DeepSeek</option>
            <option value="kimi">Kimi</option>
          </select>
        </Field>
        <Field label="实际模型">
          <select onChange={(e) => filter("model", e.target.value)}>
            <option value="">全部模型</option>
            {modelIds.map((m) => (
              <option key={m}>{m}</option>
            ))}
          </select>
        </Field>
        <Field label="阶段">
          <select onChange={(e) => filter("phase", e.target.value)}>
            <option value="">全部阶段</option>
            <option value="routing">路由分类</option>
            <option value="completion">业务执行</option>
          </select>
        </Field>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="stats">
        {[
          ["确认 token", num(s.total_tokens), "不含未知用量"],
          [
            "业务请求",
            num(s.business_requests),
            `${num(s.upstream_calls)} 次上游调用`,
          ],
          [
            "业务成功率",
            s.success_rate == null
              ? "—"
              : (s.success_rate * 100).toFixed(1) + "%",
            `${num(s.request_failed)} 次失败 · ${num(s.request_interrupted)} 次中断`,
          ],
          ["未知用量", num(s.usage_unknown), "缺失 usage 的上游调用"],
        ].map(([label, value, subtitle], i) => (
          <section
            key={label}
            className={"stat " + (i === 0 ? "accent-stat" : "")}
          >
            <span>{label}</span>
            <strong>{value}</strong>
            <small>{subtitle}</small>
          </section>
        ))}
      </div>
      <div className="two-columns">
        <section className="panel flow-panel">
          <h2>用量组成</h2>
          <div className="token-flow">
            <div>
              <small>输入 token</small>
              <strong>{num(s.input_tokens)}</strong>
            </div>
            <span>+</span>
            <div>
              <small>输出 token</small>
              <strong>{num(s.output_tokens)}</strong>
            </div>
          </div>
          <p className="hint">
            缓存命中 {num(s.cached_tokens)} · 推理 {num(s.reasoning_tokens)} ·
            图片 {num(s.image_tokens)}
            <br />
            明细为输入或输出的子项，不重复相加。
          </p>
        </section>
        <section className="panel flow-panel">
          <h2>路由开销</h2>
          <div className="routing-total">
            <strong>{num(routeTokens)}</strong>
            <span>
              token /{" "}
              {s.total_tokens
                ? ((routeTokens / s.total_tokens) * 100).toFixed(1)
                : "0"}
              %
            </span>
          </div>
          <div className="bar">
            <i
              style={{
                width: `${s.total_tokens ? (routeTokens / s.total_tokens) * 100 : 0}%`,
              }}
            />
          </div>
          <p className="hint">
            分类调用与业务执行分别计量，按实际使用的模型汇总。
          </p>
        </section>
      </div>
      <section className="panel">
        <div className="panel-heading">
          <h2>月度用量明细</h2>
          <span>{data?.month} · Asia/Shanghai</span>
        </div>
        {data?.rows.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  {[
                    "公司 / 应用",
                    "环境",
                    "实际模型",
                    "阶段",
                    "请求 / 调用",
                    "输入",
                    "输出",
                    "总 token",
                    "未知",
                  ].map((x) => (
                    <th key={x}>{x}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r: Row, i: number) => (
                  <tr key={i}>
                    <td>
                      {r.company}
                      <small>{r.application}</small>
                    </td>
                    <td>{r.environment}</td>
                    <td className="mono">{r.model}</td>
                    <td>
                      <Badge on={r.phase === "completion"}>
                        {r.phase === "routing" ? "路由分类" : "业务执行"}
                      </Badge>
                    </td>
                    <td>
                      {r.business_requests} / {r.upstream_calls}
                    </td>
                    <td>{num(r.input_tokens)}</td>
                    <td>{num(r.output_tokens)}</td>
                    <td>{num(r.total_tokens)}</td>
                    <td>{r.usage_unknown}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty>当前筛选条件下暂无调用。可以前往调试台发起第一次请求。</Empty>
        )}
      </section>
      <p className="hint">
        业务请求按请求 ID
        去重，分组请求数不能直接相加。未知用量以空值呈现；本页不是供应商结算账单。
      </p>
    </>
  );
}

function Calls({
  revision,
  keys,
  grantName,
  companies,
  apps,
}: {
  revision: number;
  keys: Row[];
  grantName: (id: string) => string;
  companies: Row[];
  apps: Row[];
}) {
  const [calls, setCalls] = useState<Row[]>([]),
    [detail, setDetail] = useState<Row | null>(null),
    [error, setError] = useState("");
  const [localRev, setRev] = useState(0),
    [offset, setOffset] = useState(0),
    [filter, setFilter] = useState<Row>({});
  const [answer, setAnswer] = useState(""),
    [usage, setUsage] = useState<Row | null>(null),
    [busy, setBusy] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const [image, setImage] = useState("");
  const query = new URLSearchParams({
    ...filter,
    offset: String(offset),
  }).toString();
  useEffect(() => {
    api("/requests?" + query)
      .then(setCalls)
      .catch((e) => setError(e.message));
  }, [revision, localRev, query]);
  useEffect(() => () => abort.current?.abort(), []);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    setError("");
    setAnswer("");
    setUsage(null);
    setBusy(true);
    abort.current = new AbortController();
    try {
      const text = String(f.get("prompt"));
      const request: Row = {
        model: f.get("model"),
        stream: true,
        stream_options: { include_usage: true },
        messages: [
          {
            role: "user",
            content: image
              ? [
                  { type: "text", text },
                  { type: "image_url", image_url: { url: image } },
                ]
              : text,
          },
        ],
      };
      if (f.get("format") === "json_object")
        request.response_format = { type: "json_object" };
      if (f.get("format") === "json_schema")
        request.response_format = {
          type: "json_schema",
          json_schema: {
            name: "answer",
            strict: true,
            schema: {
              type: "object",
              properties: { answer: { type: "string" } },
              required: ["answer"],
              additionalProperties: false,
            },
          },
        };
      await debugCall(
        String(f.get("key")),
        request,
        abort.current.signal,
        (chunk) => {
          if (chunk.usage) setUsage(chunk.usage);
          for (const c of chunk.choices || [])
            if (c.delta?.content) setAnswer((s) => s + c.delta.content);
        },
      );
    } catch (e) {
      setError(
        (e as Error).name === "AbortError"
          ? "已停止。请在调用记录中核对用量状态。"
          : (e as Error).message,
      );
    } finally {
      setBusy(false);
      setRev((n) => n + 1);
    }
  }
  return (
    <>
      <div className="two-columns">
        <section className="panel playground">
          <div className="panel-heading">
            <h2>调试台</h2>
            <Badge>计入真实用量</Badge>
          </div>
          <form onSubmit={submit}>
            <Field label="公司 / 应用 / 密钥">
              <select name="key" required>
                {keys.map((k) => (
                  <option key={k.id} value={k.id}>
                    {grantName(k.grant_id)} · {k.name} · {k.environment}
                  </option>
                ))}
              </select>
            </Field>
            <div className="inline">
              <Field label="模型">
                <select name="model">
                  <option>auto</option>
                  {modelIds.map((m) => (
                    <option key={m}>{m}</option>
                  ))}
                </select>
              </Field>
              <Field label="输出格式">
                <select name="format">
                  <option value="text">文本</option>
                  <option value="json_object">JSON Object</option>
                  <option value="json_schema">JSON Schema</option>
                </select>
              </Field>
            </div>
            <Field label="输入">
              <textarea
                name="prompt"
                rows={5}
                required
                placeholder="输入任务；选择 JSON 输出时，请在这里说明希望返回的 JSON 内容。"
              />
            </Field>
            <Field label="图片（可选，最大 5 MiB）">
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp,image/gif"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (!file) {
                    setImage("");
                    return;
                  }
                  if (file.size > 5 * 1024 * 1024) {
                    setError("图片不能超过 5 MiB");
                    e.target.value = "";
                    setImage("");
                    return;
                  }
                  const reader = new FileReader();
                  reader.onload = () => setImage(String(reader.result));
                  reader.readAsDataURL(file);
                }}
              />
            </Field>
            <div className="inline">
              <button className="primary" disabled={busy || !keys.length}>
                <Send size={15} />
                {busy ? "响应中…" : "发起调用"}
              </button>
              {busy && (
                <button
                  type="button"
                  className="secondary"
                  onClick={() => abort.current?.abort()}
                >
                  停止
                </button>
              )}
            </div>
          </form>
        </section>
        <section className="panel playground">
          <div className="panel-heading">
            <h2>模型响应</h2>
            <span>仅保留在当前页面</span>
          </div>
          {answer ? (
            <pre className="answer">{answer}</pre>
          ) : (
            <Empty>{busy ? "正在等待上游响应…" : "响应会实时显示在这里"}</Empty>
          )}
          {usage && (
            <p className="hint">
              输入 {num(usage.prompt_tokens)} · 输出{" "}
              {num(usage.completion_tokens)} · 合计 {num(usage.total_tokens)}{" "}
              token
            </p>
          )}
        </section>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <section className="panel">
        <div className="panel-heading">
          <h2>调用记录</h2>
          <div className="inline">
            <select
              aria-label="调用公司筛选"
              onChange={(e) => {
                setFilter((f) => ({ ...f, company_id: e.target.value }));
                setOffset(0);
              }}
            >
              <option value="">全部公司</option>
              {companies.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
            <select
              aria-label="调用应用筛选"
              onChange={(e) => {
                setFilter((f) => ({ ...f, application_id: e.target.value }));
                setOffset(0);
              }}
            >
              <option value="">全部应用</option>
              {apps.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
            <select
              aria-label="调用状态筛选"
              onChange={(e) => {
                setFilter((f) => ({ ...f, status: e.target.value }));
                setOffset(0);
              }}
            >
              <option value="">全部状态</option>
              {[
                "succeeded",
                "failed",
                "cancelled",
                "interrupted",
                "running",
              ].map((x) => (
                <option key={x}>{x}</option>
              ))}
            </select>
          </div>
        </div>
        {calls.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>受理时间</th>
                  <th>归属</th>
                  <th>请求模型 → 实际模型</th>
                  <th>选路原因</th>
                  <th>状态</th>
                  <th>详情</th>
                </tr>
              </thead>
              <tbody>
                {calls.map((c) => (
                  <tr key={c.id}>
                    <td>
                      {stamp(c.started_at)}
                      <small className="mono">{c.id.slice(0, 12)}</small>
                    </td>
                    <td>
                      {grantName(c.grant_id)}
                      <small>{c.environment}</small>
                    </td>
                    <td className="mono">
                      {c.requested_model}
                      <small>
                        {c.routing.execution_skipped
                          ? `仅预览：${c.routing.selected_model}`
                          : `→ ${c.actual_model || "—"}`}
                      </small>
                    </td>
                    <td>{c.routing.reason || c.error_code || "—"}</td>
                    <td>
                      <Badge on={c.status === "succeeded"}>{c.status}</Badge>
                    </td>
                    <td>
                      <button
                        onClick={() =>
                          api("/requests/" + c.id)
                            .then(setDetail)
                            .catch((e) => setError(e.message))
                        }
                      >
                        查看
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty>暂无调用记录</Empty>
        )}
        <div className="pagination">
          <button
            disabled={!offset}
            onClick={() => setOffset((n) => Math.max(0, n - 50))}
          >
            上一页
          </button>
          <span>第 {offset / 50 + 1} 页</span>
          <button
            disabled={calls.length < 50}
            onClick={() => setOffset((n) => n + 50)}
          >
            下一页
          </button>
        </div>
      </section>
      {detail && (
        <section className="panel detail">
          <div className="panel-heading">
            <h2>请求详情</h2>
            <button aria-label="关闭详情" onClick={() => setDetail(null)}>
              <X size={18} />
            </button>
          </div>
          <pre>{JSON.stringify(detail, null, 2)}</pre>
        </section>
      )}
    </>
  );
}
