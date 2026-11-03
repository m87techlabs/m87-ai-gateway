import { Activity, AlertTriangle, Check, CheckCircle2, Copy, Info, RefreshCw, X, XCircle } from "lucide-react";
import {
  cloneElement,
  createContext,
  isValidElement,
  useCallback,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type ReactElement,
  type ReactNode,
} from "react";
import { ApiError, message as errorMessage } from "../api";

type Variant = "primary" | "secondary" | "ghost" | "danger";

export function Button({
  variant = "secondary",
  small,
  icon,
  children,
  type = "button",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; small?: boolean; icon?: ReactNode }) {
  return (
    <button type={type} className={`button ${variant}${small ? " small" : ""}`} {...props}>
      {icon}
      {children}
    </button>
  );
}

export function Card({
  title,
  description,
  actions,
  children,
  className = "",
}: {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-head">
          <div>
            {title && <h2>{title}</h2>}
            {description && <p className="muted">{description}</p>}
          </div>
          {actions && <div className="row">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  eyebrow?: ReactNode;
}) {
  return (
    <header className="page-head">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {description && <p className="muted">{description}</p>}
      </div>
      {actions && <div className="row">{actions}</div>}
    </header>
  );
}

export function Field({
  label,
  help,
  children,
}: {
  label: string;
  help?: ReactNode;
  children: ReactNode;
}) {
  const id = useId();
  const helpId = help ? `${id}-help` : undefined;
  const native = isValidElement(children) && ["input", "select", "textarea"].includes(children.type as string);
  return (
    <div className="field">
      <label className="field-label" id={`${id}-label`} htmlFor={native ? id : undefined}>
        {label}
      </label>
      {native ? (
        cloneElement(children as ReactElement<Record<string, unknown>>, { id, "aria-describedby": helpId })
      ) : (
        <div role="group" aria-labelledby={`${id}-label`} aria-describedby={helpId}>
          {children}
        </div>
      )}
      {help && (
        <small className="muted" id={helpId}>
          {help}
        </small>
      )}
    </div>
  );
}

export function Switch({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      className={`switch${checked ? " on" : ""}`}
      onClick={() => onChange(!checked)}
    >
      <span />
    </button>
  );
}

export type Tone = "good" | "warning" | "critical" | "neutral" | "info";

const toneIcon = {
  good: <CheckCircle2 size={13} aria-hidden />,
  warning: <AlertTriangle size={13} aria-hidden />,
  critical: <XCircle size={13} aria-hidden />,
  neutral: null,
  info: null,
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={`badge ${tone}`}>
      {toneIcon[tone]}
      {children}
    </span>
  );
}

export function Notice({
  tone = "info",
  title,
  children,
  action,
}: {
  tone?: "info" | "warning" | "critical" | "good";
  title?: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
}) {
  const icon = {
    info: <Info size={16} aria-hidden />,
    warning: <AlertTriangle size={16} aria-hidden />,
    critical: <XCircle size={16} aria-hidden />,
    good: <CheckCircle2 size={16} aria-hidden />,
  }[tone];
  return (
    <div className={`notice ${tone}`} role={tone === "critical" ? "alert" : "status"}>
      {icon}
      <div className="notice-body">
        {title && <strong>{title}</strong>}
        {children && <div>{children}</div>}
      </div>
      {action}
    </div>
  );
}

export function ErrorNotice({ error, retry }: { error: unknown; retry?: () => void }) {
  // The console-wide banner already covers an outage, so pages keep their last data in peace.
  if (error instanceof ApiError && error.status === 0) return null;
  return (
    <Notice
      tone="critical"
      title="This could not be loaded"
      action={
        retry && (
          <Button small icon={<RefreshCw size={14} aria-hidden />} onClick={retry}>
            Try again
          </Button>
        )
      }
    >
      {errorMessage(error)}
    </Notice>
  );
}

export const Empty = ({ title, children }: { title: string; children?: ReactNode }) => (
  <div className="empty">
    <strong>{title}</strong>
    {children && <div className="muted">{children}</div>}
  </div>
);

export const Skeleton = ({ lines = 3 }: { lines?: number }) => (
  <div className="skeleton" aria-busy="true" aria-label="Loading">
    {Array.from({ length: lines }, (_, index) => (
      <span key={index} />
    ))}
  </div>
);

export const Stat = ({
  label,
  value,
  detail,
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
}) => (
  <div className="card stat">
    <span className="muted">{label}</span>
    <strong>{value}</strong>
    {detail && <small className="muted">{detail}</small>}
  </div>
);

export interface Column<T> {
  header: string;
  render: (row: T) => ReactNode;
  numeric?: boolean;
  className?: string;
}

export function Table<T>({
  columns,
  rows,
  rowKey,
  onRow,
  empty,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  onRow?: (row: T) => void;
  empty?: ReactNode;
}) {
  if (!rows.length) return <>{empty ?? <Empty title="Nothing here yet" />}</>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.header} className={column.numeric ? "numeric" : undefined}>
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={rowKey(row)}
              className={onRow ? "clickable" : undefined}
              tabIndex={onRow ? 0 : undefined}
              onClick={onRow ? () => onRow(row) : undefined}
              onKeyDown={
                onRow
                  ? (event) => {
                      if (event.key === "Enter") onRow(row);
                    }
                  : undefined
              }
            >
              {columns.map((column) => (
                <td
                  key={column.header}
                  className={[column.numeric ? "numeric" : "", column.className ?? ""].join(" ").trim() || undefined}
                >
                  {column.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Dialog({
  title,
  description,
  onClose,
  children,
  side,
  wide,
}: {
  title: ReactNode;
  description?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  side?: boolean;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const element = ref.current;
    if (element && !element.open) element.showModal();
    return () => element?.close();
  }, []);
  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      className={`dialog${side ? " side" : ""}${wide ? " wide" : ""}`}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <header className="dialog-head">
        <div>
          <h2 id={titleId}>{title}</h2>
          {description && <p className="muted">{description}</p>}
        </div>
        <Button variant="ghost" small aria-label="Close" onClick={onClose} icon={<X size={16} aria-hidden />} />
      </header>
      <div className="dialog-body">{children}</div>
    </dialog>
  );
}

export function CopyButton({ value, label = "Copy" }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      small
      icon={copied ? <Check size={14} aria-hidden /> : <Copy size={14} aria-hidden />}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1500);
        } catch {
          setCopied(false);
        }
      }}
    >
      {copied ? "Copied" : label}
    </Button>
  );
}

export const Secret = ({ value, children }: { value: string; children?: ReactNode }) => (
  <div className="secret" role="status" aria-live="polite">
    <strong>Copy this now. It is shown only once.</strong>
    <div className="secret-row">
      <code>{value}</code>
      <CopyButton value={value} />
    </div>
    {children}
  </div>
);

interface ToastItem {
  id: number;
  text: string;
  tone: "good" | "critical";
}

interface Feedback {
  success: (text: string) => void;
  failure: (error: unknown) => void;
}

const ToastContext = createContext<Feedback | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const next = useRef(0);
  const dismiss = useCallback((id: number) => setToasts((items) => items.filter((item) => item.id !== id)), []);
  const push = useCallback(
    (text: string, tone: ToastItem["tone"]) => {
      const id = ++next.current;
      setToasts((items) => [...items.slice(-3), { id, text, tone }]);
      // Failures stay until dismissed, so a quick glance away cannot lose them.
      if (tone === "good") window.setTimeout(() => dismiss(id), 4000);
    },
    [dismiss],
  );
  const value = useRef<Feedback>({
    success: (text) => push(text, "good"),
    failure: (error) => push(errorMessage(error), "critical"),
  });
  return (
    <ToastContext.Provider value={value.current}>
      {children}
      <div className="toasts" aria-live="polite">
        {toasts.map((toast) => (
          <div key={toast.id} className={`toast ${toast.tone}`} role={toast.tone === "critical" ? "alert" : "status"}>
            {toast.tone === "good" ? <CheckCircle2 size={16} aria-hidden /> : <XCircle size={16} aria-hidden />}
            <span>{toast.text}</span>
            <button type="button" aria-label="Dismiss" onClick={() => dismiss(toast.id)}>
              <X size={14} aria-hidden />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => {
  const value = useContext(ToastContext);
  if (!value) throw new Error("useToast needs ToastProvider");
  return value;
};

interface ConfirmOptions {
  title: string;
  body: ReactNode;
  action: string;
  danger?: boolean;
}

type Confirm = (options: ConfirmOptions) => Promise<boolean>;
const ConfirmContext = createContext<Confirm | null>(null);

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<(ConfirmOptions & { resolve: (value: boolean) => void }) | null>(null);
  const confirm = useCallback<Confirm>(
    (options) => new Promise((resolve) => setState({ ...options, resolve })),
    [],
  );
  const finish = (value: boolean) => {
    state?.resolve(value);
    setState(null);
  };
  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {state && (
        <Dialog title={state.title} onClose={() => finish(false)}>
          <div className="stack">
            <div>{state.body}</div>
            <div className="row end">
              <Button onClick={() => finish(false)}>Cancel</Button>
              <Button variant={state.danger ? "danger" : "primary"} onClick={() => finish(true)}>
                {state.action}
              </Button>
            </div>
          </div>
        </Dialog>
      )}
    </ConfirmContext.Provider>
  );
}

export const useConfirm = () => {
  const value = useContext(ConfirmContext);
  if (!value) throw new Error("useConfirm needs ConfirmProvider");
  return value;
};

export const LiveDot = ({ paused }: { paused?: boolean }) => (
  <span className={`live${paused ? " paused" : ""}`}>
    {paused ? <Activity size={12} aria-hidden /> : <i aria-hidden />}
    {paused ? "Paused" : "Updating live"}
  </span>
);
