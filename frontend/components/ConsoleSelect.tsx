"use client";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { Check, ChevronDown } from "lucide-react";
import s from "./field.module.css";

export type Option = { value: string; label: string };

/**
 * Drop-down styled as part of the ship console. A native <select> opens the operating
 * system's grey list, which breaks the look; this is the WAI-ARIA "select-only combobox"
 * pattern: a button that opens a listbox, fully usable from the keyboard.
 */
export default function ConsoleSelect({
  label,
  value,
  options,
  onChange,
  className = "",
}: {
  label: string;
  value: string;
  options: Option[];
  onChange: (value: string) => void;
  className?: string;
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const selectedIndex = Math.max(0, options.findIndex((o) => o.value === value));

  function show() {
    setActive(selectedIndex);
    setOpen(true);
  }
  function close(focusButton: boolean) {
    setOpen(false);
    if (focusButton) button.current?.focus();
  }
  function choose(i: number) {
    onChange(options[i].value);
    close(true);
  }

  useEffect(() => {
    if (!open) return;
    list.current?.focus();
    // Clicking anywhere else closes the list, as a native select does.
    const outside = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) close(false);
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open]);

  useEffect(() => {
    if (open) list.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active, open]);

  function onButtonKey(e: KeyboardEvent) {
    if (["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) {
      e.preventDefault();
      show();
    }
  }
  function onListKey(e: KeyboardEvent) {
    const last = options.length - 1;
    const moves: Record<string, () => void> = {
      ArrowDown: () => setActive((i) => Math.min(last, i + 1)),
      ArrowUp: () => setActive((i) => Math.max(0, i - 1)),
      Home: () => setActive(0),
      End: () => setActive(last),
      Enter: () => choose(active),
      " ": () => choose(active),
      Escape: () => close(true),
      Tab: () => close(false),
    };
    const move = moves[e.key];
    if (!move) return;
    if (e.key !== "Tab") e.preventDefault();
    move();
  }

  return (
    <div className={`${s.control} ${className}`} ref={root}>
      <span id={`${id}-label`}>{label}</span>
      <div className={s.select}>
        <button
          ref={button}
          type="button"
          className={s.selectButton}
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-controls={`${id}-list`}
          aria-labelledby={`${id}-label ${id}-value`}
          onClick={() => (open ? close(true) : show())}
          onKeyDown={onButtonKey}
        >
          <span id={`${id}-value`}>{options[selectedIndex]?.label}</span>
          <ChevronDown aria-hidden="true" data-open={open} />
        </button>
        {open && (
          <ul
            ref={list}
            id={`${id}-list`}
            role="listbox"
            tabIndex={-1}
            className={s.listbox}
            aria-labelledby={`${id}-label`}
            aria-activedescendant={`${id}-opt-${active}`}
            onKeyDown={onListKey}
          >
            {options.map((o, i) => (
              <li
                key={o.value}
                id={`${id}-opt-${i}`}
                data-index={i}
                role="option"
                aria-selected={o.value === value}
                data-active={i === active}
                onPointerEnter={() => setActive(i)}
                onClick={() => choose(i)}
              >
                <span>{o.label}</span>
                {o.value === value && <Check aria-hidden="true" />}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
