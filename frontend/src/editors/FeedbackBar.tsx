import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useEffect, useState } from "react";
import { sendFeedback } from "../api";
import { Button } from "../ui";

/** Helpful / not helpful on the current version, with an optional reason. */
export function FeedbackBar({ artifactId, version }: { artifactId: string; version: number }) {
  const [state, setState] = useState<"idle" | "asking" | "sending" | "sent" | "error">("idle");
  const [note, setNote] = useState("");

  useEffect(() => {
    setState("idle");
    setNote("");
  }, [artifactId, version]);

  async function submit(rating: "up" | "down", reason = "") {
    setState("sending");
    try {
      await sendFeedback(artifactId, rating, reason);
      setState("sent");
    } catch {
      setState("error");
    }
  }

  if (state === "sent") return <span className="text-xs text-muted">Thanks, noted.</span>;
  if (state === "asking") {
    return (
      <span className="flex items-center gap-1.5">
        <input
          aria-label="What should be different?"
          autoFocus
          className="w-48 rounded border border-line-strong bg-surface px-2 py-1 text-xs"
          placeholder="What should be different?"
          value={note}
          onChange={(event) => setNote(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") void submit("down", note);
            if (event.key === "Escape") setState("idle");
          }}
        />
        <Button onClick={() => void submit("down", note)} size="sm">
          Send
        </Button>
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1">
      <Button aria-label="Helpful" disabled={state === "sending"} onClick={() => void submit("up")} size="sm" title="Helpful">
        <ThumbsUp aria-hidden className="h-3.5 w-3.5" />
      </Button>
      <Button aria-label="Not helpful" disabled={state === "sending"} onClick={() => setState("asking")} size="sm" title="Not helpful">
        <ThumbsDown aria-hidden className="h-3.5 w-3.5" />
      </Button>
      {state === "error" && <span className="text-xs text-danger">Not saved</span>}
    </span>
  );
}
