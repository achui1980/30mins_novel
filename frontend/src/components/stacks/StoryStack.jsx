import { useState } from "react";
import StoryTab from "../tabs/StoryTab";
import StackShell from "./StackShell";

export default function StoryStack({ id, onBack }) {
  const [, setRight] = useState(null);
  return (
    <StackShell title="剧情正片" onBack={onBack}>
      <div className="px-6 py-4">
        <StoryTab id={id} setRight={setRight} />
      </div>
    </StackShell>
  );
}
