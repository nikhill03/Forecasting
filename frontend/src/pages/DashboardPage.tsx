import { Link } from "react-router-dom";
import { Upload, TrendingUp } from "lucide-react";
import { Card, CardContent } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";

export function DashboardPage() {
  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-8">
        <h1 className="text-xl font-semibold text-text">Dashboard</h1>
        <p className="mt-1 text-sm text-text-muted">
          ML-powered demand forecasting with automatic model selection.
        </p>
      </div>

      <Card>
        <CardContent className="flex flex-col items-center gap-4 py-12 text-center">
          <div className="rounded-full bg-accent/10 p-4">
            <TrendingUp className="h-8 w-8 text-accent" aria-hidden="true" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-text">
              Start a new forecast
            </h2>
            <p className="mt-1 max-w-sm text-sm text-text-muted">
              Upload a dataset and we'll automatically classify demand
              patterns and select the best forecasting model.
            </p>
          </div>
          <Link to="/upload">
            <Button size="lg">
              <Upload className="h-4 w-4" aria-hidden="true" />
              Upload dataset
            </Button>
          </Link>
        </CardContent>
      </Card>
    </div>
  );
}