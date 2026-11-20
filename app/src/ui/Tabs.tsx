import * as RTabs from "@radix-ui/react-tabs";
import type { ReactNode } from "react";

interface TabsProps {
  label: string;
  tabs: { id: string; title: string; content: ReactNode }[];
  value?: string;
  onValueChange?(id: string): void;
}

/** Pestañas con flechas del teclado (las usa el panel Ajustes/Historial del editor). */
export function Tabs({ label, tabs, value, onValueChange }: TabsProps) {
  return (
    <RTabs.Root
      className="tabs"
      value={value}
      defaultValue={value ? undefined : tabs[0]?.id}
      onValueChange={onValueChange}
    >
      <RTabs.List className="tabs-list" aria-label={label}>
        {tabs.map((t) => (
          <RTabs.Trigger key={t.id} value={t.id} className="tabs-trigger">
            {t.title}
          </RTabs.Trigger>
        ))}
      </RTabs.List>
      {tabs.map((t) => (
        <RTabs.Content key={t.id} value={t.id} className="tabs-content">
          {t.content}
        </RTabs.Content>
      ))}
    </RTabs.Root>
  );
}
