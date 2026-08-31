import { Link } from "react-router-dom";
import { Menu, LogOut, User } from "lucide-react";
import { useState } from "react";
import { useAuthStore } from "@/store/authStore";
import { Button } from "@/components/ui/Button";
import { BrandMark } from "@/components/ui/BrandMark";

interface HeaderProps {
  onMenuToggle?: () => void;
}

export function Header({ onMenuToggle }: HeaderProps) {
  const { user, isAuthenticated, logout } = useAuthStore();
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <header className="sticky top-0 z-40 flex h-14 items-center justify-between border-b border-border bg-bg/95 px-4 backdrop-blur supports-[backdrop-filter]:bg-bg/80 sm:px-6">
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={onMenuToggle}
          className="rounded-md p-2 text-text-muted hover:bg-bg-raised hover:text-text md:hidden"
          aria-label="Toggle navigation menu"
        >
          <Menu className="h-5 w-5" aria-hidden="true" />
        </button>

        <Link
          to="/dashboard"
          className="flex items-center gap-2 font-display font-semibold text-text"
        >
          <BrandMark className="h-5 w-5" />
          <span className="hidden sm:inline">Forecasting Platform</span>
        </Link>
      </div>

      <div className="relative">
        {isAuthenticated ? (
          <button
            type="button"
            onClick={() => setMenuOpen((v) => !v)}
            className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-text-muted hover:bg-bg-raised hover:text-text"
            aria-expanded={menuOpen}
            aria-haspopup="menu"
          >
            <User className="h-4 w-4" aria-hidden="true" />
            <span className="hidden sm:inline">
              {user?.full_name ?? "Account"}
            </span>
          </button>
        ) : (
          <Link to="/login">
            <Button variant="secondary" size="sm">
              Sign in
            </Button>
          </Link>
        )}

        {menuOpen && isAuthenticated && (
          <div
            role="menu"
            className="absolute right-0 top-full mt-2 w-48 animate-slide-up rounded-md border border-border bg-bg-surface py-1 shadow-lg"
          >
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                logout();
                setMenuOpen(false);
              }}
              className="flex w-full items-center gap-2 px-3 py-2 text-sm text-text-muted hover:bg-bg-raised hover:text-text"
            >
              <LogOut className="h-4 w-4" aria-hidden="true" />
              Sign out
            </button>
          </div>
        )}
      </div>
    </header>
  );
}