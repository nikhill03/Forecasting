import { Link } from "react-router-dom";
import {
  ArrowRight,
  BarChart3,
  FileSpreadsheet,
  Layers,
  SlidersHorizontal,
  Target,
  Upload,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card, CardContent } from "@/components/ui/Card";
import { BrandMark } from "@/components/ui/BrandMark";
import { DemandQuadrant } from "@/components/marketing/DemandQuadrant";

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

const STEPS = [
  {
    icon: Upload,
    title: "Upload your dataset",
    description: "Drop a CSV or Excel file. Sheets and columns are detected automatically.",
  },
  {
    icon: SlidersHorizontal,
    title: "Configure the forecast",
    description: "Pick metrics, drivers and a horizon — or run with the defaults.",
  },
  {
    icon: Target,
    title: "Get a ranked result",
    description: "Every model is scored on WMAPE; the best one is called out for you.",
  },
] as const;

export function LandingPage() {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-40 flex h-14 items-center justify-between border-b border-border bg-bg/95 px-4 backdrop-blur supports-[backdrop-filter]:bg-bg/80 sm:px-6">
        <Link to="/" className="flex items-center gap-2 font-display font-semibold text-text">
          <BrandMark className="h-5 w-5" />
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
        <section className="relative overflow-hidden px-4 py-20 sm:px-6 sm:py-28">
          <div className="mx-auto grid max-w-6xl grid-cols-1 items-center gap-14 lg:grid-cols-[1.1fr_1fr]">
            <div className="flex flex-col items-start text-left animate-fade-in">
              <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-bg-raised px-3 py-1 text-xs font-medium text-text-muted">
                <span className="h-1.5 w-1.5 rounded-full bg-accent" aria-hidden="true" />
                Ranked, multi-model demand forecasting
              </span>

              <h1 className="mt-6 font-display text-4xl font-semibold leading-[1.08] tracking-tight text-text sm:text-5xl">
                Every series, classified.
                <br />
                Every forecast, <span className="text-accent">ranked</span>.
              </h1>

              <p className="mt-5 max-w-xl text-base text-text-muted sm:text-lg">
                Upload a CSV or Excel file and the platform plots each series
                on its demand curve, trains multiple models against it, and
                scores every result by WMAPE and a composite metric — so the
                best one always wins.
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

            <div className="tick-corners rounded-lg border border-border bg-bg-surface/60 p-5 sm:p-6">
              <DemandQuadrant />
              <p className="mt-3 text-center text-xs text-text-subtle">
                Order interval × demand variability — the classification
                every uploaded series runs through before a single model trains.
              </p>
            </div>
          </div>
        </section>

        <section className="border-t border-border px-4 py-16 sm:px-6">
          <div className="mx-auto max-w-5xl">
            <h2 className="text-center text-sm font-semibold uppercase tracking-[0.12em] text-text-subtle">
              How it works
            </h2>
            <div className="mt-8 grid grid-cols-1 gap-8 sm:grid-cols-3">
              {STEPS.map(({ icon: Icon, title, description }, index) => (
                <div key={title} className="flex flex-col items-start gap-3">
                  <div className="flex items-center gap-3">
                    <span className="font-mono text-xs text-text-subtle">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <Icon className="h-4 w-4 text-accent" aria-hidden="true" />
                  </div>
                  <h3 className="text-base font-semibold text-text">{title}</h3>
                  <p className="text-sm text-text-muted">{description}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="border-t border-border px-4 py-20 sm:px-6">
          <div className="mx-auto max-w-5xl">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              {FEATURES.map(({ icon: Icon, title, description }) => (
                <Card key={title} className="tick-corners hover:border-border-strong">
                  <CardContent className="flex flex-col gap-3 py-6">
                    <div className="w-fit rounded-md bg-accent/10 p-2.5">
                      <Icon className="h-5 w-5 text-accent" aria-hidden="true" />
                    </div>
                    <h3 className="text-base font-semibold text-text">{title}</h3>
                    <p className="text-sm text-text-muted">{description}</p>
                  </CardContent>
                </Card>
              ))}
            </div>

            <div className="mt-12 flex justify-center">
              <Link to="/register">
                <Button size="lg">
                  Create your account
                  <ArrowRight className="h-4 w-4" aria-hidden="true" />
                </Button>
              </Link>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-border px-4 py-8 sm:px-6">
        <div className="mx-auto flex max-w-5xl flex-col items-center gap-2 text-center">
          <div className="flex items-center gap-2 text-text-subtle">
            <BrandMark className="h-4 w-4" />
            <span className="font-display text-sm">Forecasting Platform</span>
          </div>
          <p className="text-xs text-text-subtle">
            Multi-model demand forecasting, scored on evidence.
          </p>
        </div>
      </footer>
    </div>
  );
}
