import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { FileDropzone } from "./FileDropzone";

function makeFile(name: string, sizeBytes: number, type = "text/csv") {
  const file = new File(["x".repeat(sizeBytes)], name, { type });
  return file;
}

describe("FileDropzone", () => {
  it("renders the dropzone with instructions", () => {
    render(<FileDropzone onFileSelect={vi.fn()} />);
    expect(
      screen.getByText(/drop your dataset here/i),
    ).toBeInTheDocument();
  });

  it("is keyboard accessible (Enter opens file picker)", async () => {
    const user = userEvent.setup();
    render(<FileDropzone onFileSelect={vi.fn()} />);

    const dropzone = screen.getByRole("button");
    expect(dropzone).toHaveAttribute("tabIndex", "0");

    dropzone.focus();
    expect(dropzone).toHaveFocus();
    await user.keyboard("{Enter}");
  });

  it("calls onFileSelect with a valid CSV file", async () => {
    const handleSelect = vi.fn();
    const user = userEvent.setup();
    render(<FileDropzone onFileSelect={handleSelect} />);

    const input = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    const file = makeFile("data.csv", 100);

    await user.upload(input, file);

    expect(handleSelect).toHaveBeenCalledWith(file);
  });

  it("rejects unsupported file types via drag and drop", () => {
    const handleSelect = vi.fn();
    render(<FileDropzone onFileSelect={handleSelect} />);

    const dropzone = screen.getByRole("button");
    const file = makeFile("data.txt", 100, "text/plain");

    fireEvent.drop(dropzone, {
      dataTransfer: { files: [file] },
    });

    expect(handleSelect).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/not supported/i);
  });

  it("rejects files exceeding the size limit", () => {
    const handleSelect = vi.fn();
    render(<FileDropzone onFileSelect={handleSelect} />);

    const dropzone = screen.getByRole("button");
    const bigFile = makeFile("huge.csv", 51 * 1024 * 1024);

    fireEvent.drop(dropzone, {
      dataTransfer: { files: [bigFile] },
    });

    expect(handleSelect).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/exceeds/i);
  });

  it("displays external error prop", () => {
    render(
      <FileDropzone onFileSelect={vi.fn()} error="Server rejected file" />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Server rejected file",
    );
  });

  it("shows uploading state and disables interaction", () => {
    render(<FileDropzone onFileSelect={vi.fn()} isUploading />);
    expect(screen.getByText(/uploading/i)).toBeInTheDocument();
  });
});