"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { Menu, X, PlusCircle, History, Database, Sparkles, LayoutDashboard } from "lucide-react";

const NAV_ITEMS = [
  { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
  { label: "New Task", href: "/", icon: PlusCircle },
  { label: "History", href: "/history", icon: History },
  { label: "Datasets", href: "/datasets", icon: Database },
];

export function Sidebar() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Open navigation"
        className="fixed left-4 top-4 z-40 rounded-lg border border-border-subtle bg-elevated p-2 text-text-secondary shadow-lg md:hidden"
      >
        <Menu className="h-5 w-5" />
      </button>
      {open && (
        <button
          type="button"
          aria-label="Close navigation"
          onClick={() => setOpen(false)}
          className="fixed inset-0 z-40 bg-black/60 md:hidden"
        />
      )}
      <aside className={`fixed inset-y-0 left-0 z-50 w-56 shrink-0 flex flex-col border-r border-border-subtle bg-elevated transition-transform md:sticky md:top-0 md:z-auto md:h-screen md:translate-x-0 ${open ? "translate-x-0" : "-translate-x-full"}`}>
      <div className="flex items-center justify-between gap-2 px-5 h-16 border-b border-border-subtle">
        <div className="flex items-center gap-2">
        <Sparkles className="h-5 w-5 text-cyan" />
        <span className="font-heading font-semibold text-sm">
          <span className="text-cyan">DataForge</span>
          <span className="text-text-primary"> AI</span>
        </span>
        </div>
        <button
          type="button"
          onClick={() => setOpen(false)}
          aria-label="Close navigation"
          className="rounded p-1 text-text-muted hover:text-text-primary md:hidden"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <nav className="flex-1 px-3 py-4 flex flex-col gap-1">
        {NAV_ITEMS.map(({ label, href, icon: Icon }) => {
          const active = href === "/" ? pathname === href : pathname === href || pathname.startsWith(`${href}/`);
          return (
            <Link
              key={label}
              href={href}
              onClick={() => setOpen(false)}
              className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ${
                active
                  ? "bg-card-solid text-cyan border border-border-glow"
                  : "text-text-secondary hover:text-text-primary hover:bg-card-solid"
              }`}
            >
              <Icon className="h-4 w-4" />
              {label}
            </Link>
          );
        })}
      </nav>
    </aside>
    </>
  );
}