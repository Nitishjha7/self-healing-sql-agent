import {
  IconActivity,
  IconBrain,
  IconCheck,
  IconRefresh,
  IconShield,
} from "./Icons.jsx";

/** The claims strip along the bottom. Each one is a thing the system does. */
const FEATURES = [
  { Icon: IconRefresh, title: "Self-healing", sub: "Up to 3 automatic retries" },
  { Icon: IconShield, title: "Safe by design", sub: "Writes need your approval" },
  { Icon: IconBrain, title: "Conversation memory", sub: "Context across questions" },
  { Icon: IconCheck, title: "Validation layer", sub: "Guards the final answer" },
  { Icon: IconActivity, title: "Observability", sub: "LangSmith tracing ready" },
];

export default function FeatureStrip() {
  return (
    <footer className="feature-strip">
      {FEATURES.map(({ Icon, title, sub }) => (
        <div className="feature" key={title}>
          <span className="feature-icon">
            <Icon size={14} />
          </span>
          <div>
            <strong>{title}</strong>
            <small>{sub}</small>
          </div>
        </div>
      ))}
    </footer>
  );
}
