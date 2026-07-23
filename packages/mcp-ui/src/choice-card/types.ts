export interface ChoiceCardPayload {
  prompt: string;
  options: string[];
  title?: string | null;
}

export interface ChoiceCardProps {
  /** The structured payload from data360_interactive_choices tool output. */
  payload: ChoiceCardPayload;
  /**
   * Called when the user clicks a choice or submits a "specify" value.
   * The host is responsible for sending this text as a user message.
   */
  onSelect: (text: string) => void;
  /** Light or dark theme. Defaults to "light". */
  theme?: "light" | "dark";
  /** Extra CSS class applied to the outer wrapper. */
  className?: string;
}
