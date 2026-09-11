/**
 * A small "?" beside a label: one sentence on why Scaleezy asks for this.
 *
 * Opens on hover for a mouse and on tap for a thumb — a Popover, because a
 * Tooltip never opens on touch. Never holds instructions the person needs
 * to fill the field; those stay in the hint below it.
 */
import { HelpCircle } from "lucide-react";
import { useState } from "react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

export function Why({ children }: { children: string }) {
  const [open, setOpen] = useState(false);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label="Why do we ask for this?"
          onMouseEnter={() => setOpen(true)}
          onMouseLeave={() => setOpen(false)}
          className="ml-1.5 inline-grid size-4 place-items-center rounded-full align-middle text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          <HelpCircle className="size-3.5" strokeWidth={2} aria-hidden />
        </button>
      </PopoverTrigger>
      <PopoverContent
        side="top"
        align="start"
        className="w-64 px-3 py-2 text-xs leading-relaxed font-normal normal-case tracking-normal"
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
      >
        {children}
      </PopoverContent>
    </Popover>
  );
}
