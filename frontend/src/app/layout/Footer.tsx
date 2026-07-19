import { useApplication } from "@/contexts/ApplicationContext";

export function Footer() {
  const { info } = useApplication();
  return (
    <footer
      className="flex h-8 items-center justify-between border-t border-border bg-surface px-4 text-xs text-text-subtle"
      data-testid="footer"
    >
      <span>{info.name} v{info.version}</span>
      <span>Interface web — infraestrutura preparatória</span>
    </footer>
  );
}
