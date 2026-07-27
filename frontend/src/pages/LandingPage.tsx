import { Link } from "react-router-dom";
import {
  Activity,
  ArrowRight,
  BarChart3,
  FileSpreadsheet,
  Layers,
  Target,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card, CardContent } from "@/components/ui/Card";

const FEATURES = [
  {
    icon: BarChart3,
    title: "Multi-model forecasting",
    description:
      "Univariate and multivariate models compete automatically — Ridge, Lasso, XGBoost and more — so you don't have to pick one.",
  },
  {
    icon: Target,
    title: "WMAPE + composite scoring",
    description:
      "Every model is ranked on WMAPE and a composite metric, so the champion model is chosen on evidence, not guesswork.",
  },
  {
    icon: Layers,
    title: "Automatic demand classification",
    description:
      "Series are classified Smooth, Erratic, Intermittent or Lumpy, and the right model family is recommended for each.",
  },
  {
    icon: FileSpreadsheet,
    title: "CSV & Excel, no prep needed",
    description:
      "Upload a raw file, pick your sheets and columns, and configure the forecast horizon — the pipeline handles the rest.",
  },
] as const;

export function LandingPage() {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-40 flex h-14 items-center justify-between border-b border-border bg-bg/95 px-4 backdrop-blur supports-[backdrop-filter]:bg-bg/80 sm:px-6">
        <Link to="/" className="flex items-center gap-2 font-semibold text-text">
          <Activity className="h-5 w-5 text-accent" aria-hidden="true" />
          <span>Forecasting Platform</span>
        </Link>

        <div className="flex items-center gap-2">
          <Link to="/login">
            <Button variant="secondary" size="sm">
              Login
            </Button>
          </Link>
          <Link to="/register">
            <Button variant="primary" size="sm">
              Register
            </Button>
          </Link>
        </div>
      </header>

      <main className="flex-1">
        <section className="relative overflow-hidden px-4 py-24 sm:px-6 sm:py-32">
          <div
            aria-hidden="true"
            className="pointer-events-none absolute left-1/2 top-0 -z-10 h-[36rem] w-[36rem] -translate-x-1/2 -translate-y-1/3 rounded-full bg-accent/20 blur-3xl animate-pulse-slow"
          />

          <div className="mx-auto flex max-w-2xl flex-col items-center text-center animate-fade-in">
            <span className="rounded-full border border-border bg-bg-raised px-3 py-1 text-xs font-medium text-text-muted">
              Ranked, multi-model demand forecasting
            </span>

            <h1 className="mt-6 text-4xl font-semibold tracking-tight text-text sm:text-5xl">
              Forecast demand with{" "}
              <span className="text-accent">confidence</span>, not guesswork
            </h1>

            <p className="mt-4 max-w-xl text-base text-text-muted sm:text-lg">
              Upload a CSV or Excel file, configure your forecast, and let the
              platform train and rank multiple models for you — scored by
              WMAPE and a composite metric, so the best one always wins.
            </p>

            <div className="mt-8 flex flex-col gap-3 sm:flex-row animate-slide-up">
              <Link to="/register">
                <Button size="lg">
                  Get started
                  <ArrowRight className="h-4 w-4" aria-hidden="true" />
                </Button>
              </Link>
              <Link to="/login">
                <Button variant="secondary" size="lg">
                  Sign in
                </Button>
              </Link>
            </div>
          </div>
        </section>

        <section className="px-4 pb-24 sm:px-6">
          <div className="mx-auto grid max-w-5xl grid-cols-1 gap-4 sm:grid-cols-2">
            {FEATURES.map(({ icon: Icon, title, description }) => (
              <Card key={title} className="transition-colors hover:border-border-strong">
                <CardContent className="flex flex-col gap-3 py-6">
                  <div className="w-fit rounded-full bg-accent/10 p-3">
                    <Icon className="h-5 w-5 text-accent" aria-hidden="true" />
                  </div>
                  <h2 className="text-base font-semibold text-text">{title}</h2>
                  <p className="text-sm text-text-muted">{description}</p>
                </CardContent>
              </Card>
            ))}
          </div>

          <div className="mx-auto mt-12 flex max-w-5xl justify-center">
            <Link to="/register">
              <Button size="lg">
                Create your account
                <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </Button>
            </Link>
          </div>
        </section>
      </main>
    </div>
  );
}
