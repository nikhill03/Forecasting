import { useNavigate } from "react-router-dom";
import { useEffect } from "react";
import { FileDropzone } from "@/components/upload/FileDropzone";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { useUpload } from "@/hooks/useUpload";
import { useForecastStore } from "@/store/forecastStore";

export function UploadPage() {
  const navigate = useNavigate();
  const { upload, isUploading, progress, error } = useUpload();
  const uploadResult = useForecastStore((s) => s.upload);

  useEffect(() => {
    if (uploadResult) {
      navigate("/configure");
    }
  }, [uploadResult, navigate]);

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-text">New forecast</h1>
        <p className="mt-1 text-sm text-text-muted">
          Upload a dataset to get started. We'll automatically detect sheets
          and columns.
        </p>
      </div>

      <Card className="tick-corners">
        <CardHeader>
          <CardTitle>Upload dataset</CardTitle>
        </CardHeader>
        <CardContent>
          <FileDropzone
            onFileSelect={upload}
            isUploading={isUploading}
            error={error}
          />
          {isUploading && progress > 0 && (
            <ProgressBar
              value={progress}
              label="Uploading"
              className="mt-4"
            />
          )}
        </CardContent>
      </Card>
    </div>
  );
}