import * as RT from "@radix-ui/react-tooltip";
import type { ReactNode } from "react";

export const TooltipProvider = ({ children }: { children: ReactNode }) => (
  <RT.Provider delayDuration={450} skipDelayDuration={200}>
    {children}
  </RT.Provider>
);

export function Tooltip({ text, children }: { text: string; children: ReactNode }) {
  return (
    <RT.Root>
      <RT.Trigger asChild>{children}</RT.Trigger>
      <RT.Portal>
        <RT.Content className="tooltip" sideOffset={6}>
          {text}
        </RT.Content>
      </RT.Portal>
    </RT.Root>
  );
}
