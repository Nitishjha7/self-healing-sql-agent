import { IconSend } from "../components/Icons.jsx";

/** The question input. Sticky to the bottom of the chat column. */

export default function Composer({ input, setInput, onSubmit, loading }) {
  return (
    <form
      className="composer"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <div className="composer-box">
        <input
          className="input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask a follow-up question…"
          disabled={loading}
          autoFocus
        />
        <button className="send" type="submit" disabled={loading || !input.trim()}>
          <IconSend size={16} />
        </button>
      </div>
      <p className="composer-hint">Press Enter to send</p>
    </form>
  );
}

/* ---------------------------------------------------------------- footer */
