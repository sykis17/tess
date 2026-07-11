import type { FormEvent } from "react";

interface MessageInputProps {
  disabled: boolean;
  onSend: (message: string) => void;
}

export function MessageInput({ disabled, onSend }: MessageInputProps) {
  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const input = form.elements.namedItem("message") as HTMLInputElement;
    const text = input.value.trim();

    if (!text) {
      return;
    }

    onSend(text);
    input.value = "";
  };

  return (
    <form className="message-input" onSubmit={handleSubmit}>
      <input
        type="text"
        name="message"
        placeholder="Send a message to TESS..."
        disabled={disabled}
        autoComplete="off"
      />
      <button type="submit" disabled={disabled}>
        Send
      </button>
    </form>
  );
}
