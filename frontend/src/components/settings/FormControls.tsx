/**
 * Form controls — controles de formulário reutilizáveis para Settings.
 *
 * Cada controle possui:
 * - Label
 * - Descrição/Tooltip
 * - Estado vazio/loading/erro/sucesso
 * - Acessibilidade (ARIA)
 */

import {
  type ReactNode,
  type InputHTMLAttributes,
  type SelectHTMLAttributes,
  type ButtonHTMLAttributes,
} from "react";
import { HelpCircle, Check, X, Loader2 } from "lucide-react";
import { cn } from "@/utils";

// ============================================================
// FieldShell — wrapper comum: label + descrição + erro + children.
// ============================================================

interface FieldShellProps {
  label: string;
  description?: string;
  tooltip?: string;
  error?: string;
  success?: boolean;
  loading?: boolean;
  children: ReactNode;
  htmlFor?: string;
}

export function FieldShell({
  label,
  description,
  tooltip,
  error,
  success,
  loading,
  children,
  htmlFor,
}: FieldShellProps) {
  return (
    <div className="flex flex-col gap-1.5" data-testid="field-shell">
      <div className="flex items-center gap-1.5">
        <label
          htmlFor={htmlFor}
          className="text-sm font-medium text-text"
        >
          {label}
        </label>
        {tooltip && (
          <span title={tooltip} className="text-text-subtle">
            <HelpCircle className="h-3.5 w-3.5" />
          </span>
        )}
        {loading && <Loader2 className="h-3.5 w-3.5 animate-spin text-status-processing" />}
        {success && !error && <Check className="h-3.5 w-3.5 text-status-success" />}
        {error && <X className="h-3.5 w-3.5 text-status-error" />}
      </div>
      {description && (
        <p className="text-xs text-text-muted">{description}</p>
      )}
      {children}
      {error && (
        <p className="text-xs text-status-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

// ============================================================
// TextField
// ============================================================

interface TextFieldProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "onChange"> {
  label: string;
  description?: string;
  tooltip?: string;
  error?: string;
  success?: boolean;
  loading?: boolean;
  value: string;
  onChange: (value: string) => void;
}

export function TextField({
  label,
  description,
  tooltip,
  error,
  success,
  loading,
  value,
  onChange,
  id,
  ...rest
}: TextFieldProps) {
  const fieldId = id ?? `tf-${label.replace(/\s+/g, "-").toLowerCase()}`;
  return (
    <FieldShell
      label={label}
      description={description}
      tooltip={tooltip}
      error={error}
      success={success}
      loading={loading}
      htmlFor={fieldId}
    >
      <input
        id={fieldId}
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-invalid={Boolean(error)}
        className={cn(
          "rounded-md border bg-surface px-3 py-2 text-sm text-text placeholder:text-text-subtle",
          "focus:outline-none focus:ring-2 focus:ring-accent/40",
          error ? "border-status-error" : "border-border",
        )}
        data-testid="text-field"
        {...rest}
      />
    </FieldShell>
  );
}

// ============================================================
// NumberField
// ============================================================

interface NumberFieldProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "onChange" | "value" | "type"> {
  label: string;
  description?: string;
  tooltip?: string;
  error?: string;
  success?: boolean;
  loading?: boolean;
  value: number;
  onChange: (value: number) => void;
}

export function NumberField({
  label,
  description,
  tooltip,
  error,
  success,
  loading,
  value,
  onChange,
  id,
  ...rest
}: NumberFieldProps) {
  const fieldId = id ?? `nf-${label.replace(/\s+/g, "-").toLowerCase()}`;
  return (
    <FieldShell
      label={label}
      description={description}
      tooltip={tooltip}
      error={error}
      success={success}
      loading={loading}
      htmlFor={fieldId}
    >
      <input
        id={fieldId}
        type="number"
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-invalid={Boolean(error)}
        className={cn(
          "rounded-md border bg-surface px-3 py-2 text-sm text-text",
          "focus:outline-none focus:ring-2 focus:ring-accent/40",
          error ? "border-status-error" : "border-border",
        )}
        data-testid="number-field"
        {...rest}
      />
    </FieldShell>
  );
}

// ============================================================
// SelectField
// ============================================================

interface SelectOption {
  value: string;
  label: string;
}

interface SelectFieldProps
  extends Omit<SelectHTMLAttributes<HTMLSelectElement>, "onChange" | "value"> {
  label: string;
  description?: string;
  tooltip?: string;
  error?: string;
  success?: boolean;
  loading?: boolean;
  value: string;
  options: SelectOption[];
  onChange: (value: string) => void;
}

export function SelectField({
  label,
  description,
  tooltip,
  error,
  success,
  loading,
  value,
  options,
  onChange,
  id,
  ...rest
}: SelectFieldProps) {
  const fieldId = id ?? `sf-${label.replace(/\s+/g, "-").toLowerCase()}`;
  return (
    <FieldShell
      label={label}
      description={description}
      tooltip={tooltip}
      error={error}
      success={success}
      loading={loading}
      htmlFor={fieldId}
    >
      <select
        id={fieldId}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-invalid={Boolean(error)}
        className={cn(
          "rounded-md border bg-surface px-3 py-2 text-sm text-text",
          "focus:outline-none focus:ring-2 focus:ring-accent/40",
          error ? "border-status-error" : "border-border",
        )}
        data-testid="select-field"
        {...rest}
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </FieldShell>
  );
}

// ============================================================
// Toggle — switch booleano.
// ============================================================

interface ToggleProps {
  label: string;
  description?: string;
  tooltip?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}

export function Toggle({
  label,
  description,
  tooltip,
  checked,
  onChange,
  disabled,
}: ToggleProps) {
  const toggleId = `tg-${label.replace(/\s+/g, "-").toLowerCase()}`;
  return (
    <FieldShell
      label={label}
      description={description}
      tooltip={tooltip}
      htmlFor={toggleId}
    >
      <button
        id={toggleId}
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cn(
          "relative inline-flex h-6 w-11 items-center rounded-full transition-colors",
          checked ? "bg-accent" : "bg-border",
          disabled && "opacity-50",
        )}
        data-testid="toggle"
        data-checked={checked}
      >
        <span
          className={cn(
            "inline-block h-4 w-4 transform rounded-full bg-white transition-transform",
            checked ? "translate-x-6" : "translate-x-1",
          )}
        />
      </button>
    </FieldShell>
  );
}

// ============================================================
// Button
// ============================================================

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "danger";
  loading?: boolean;
  icon?: ReactNode;
}

export function Button({
  variant = "secondary",
  loading,
  icon,
  children,
  className,
  disabled,
  ...rest
}: ButtonProps) {
  const variantClass = {
    primary: "bg-accent text-white hover:bg-accent-hover",
    secondary: "border border-border text-text hover:bg-surface-hover",
    danger: "border border-status-error text-status-error hover:bg-status-error/10",
  }[variant];

  return (
    <button
      disabled={disabled || loading}
      className={cn(
        "inline-flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors",
        "focus:outline-none focus:ring-2 focus:ring-accent/40",
        "disabled:cursor-not-allowed disabled:opacity-50",
        variantClass,
        className,
      )}
      data-testid="button"
      {...rest}
    >
      {loading ? (
        <Loader2 className="h-4 w-4 animate-spin" />
      ) : (
        icon
      )}
      {children}
    </button>
  );
}
