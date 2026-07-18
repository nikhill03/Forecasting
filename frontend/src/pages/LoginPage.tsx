import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { authService } from "@/services/authService";
import { useAuthStore } from "@/store/authStore";
import { ApiError } from "@/services/client";

export function LoginPage() {
  const navigate = useNavigate();
  const setTokens = useAuthStore((s) => s.setTokens);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsLoading(true);
    try {
      const tokens = await authService.login({ email, password });
      setTokens(tokens.access_token, tokens.refresh_token);
      navigate("/");
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Sign in failed. Please try again.",
      );
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="mx-auto flex min-h-[60vh] max-w-sm flex-col justify-center">
      <Card>
        <CardHeader>
          <CardTitle>Sign in</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="flex flex-col gap-4" noValidate>
            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-text-muted">
                Email
              </span>
              <input
                type="email"
                required
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="h-10 rounded-md border border-border bg-bg-raised px-3 text-sm text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              />
            </label>

            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-text-muted">
                Password
              </span>
              <input
                type="password"
                required
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="h-10 rounded-md border border-border bg-bg-raised px-3 text-sm text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              />
            </label>

            {error && (
              <div role="alert" className="text-sm text-danger">
                {error}
              </div>
            )}

            <Button type="submit" isLoading={isLoading} className="mt-2">
              Sign in
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}