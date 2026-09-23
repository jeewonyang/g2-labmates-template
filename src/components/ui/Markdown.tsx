import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** Renders trusted, user-authored markdown for note/resource/review bodies. */
export function Markdown({ children }: { children: string }) {
  return (
    <div className="prose-sb">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </div>
  );
}
