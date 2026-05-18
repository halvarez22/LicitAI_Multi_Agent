export type Severity = "block" | "warn" | "info";
export type ActionType =
  | "navigate"
  | "modal"
  | "auto_fix"
  | "continue_with_warning"
  | "close";

export interface ValidationAction {
  label: string;
  type: ActionType;
  target?: string;
  requires_justification?: boolean;
  skip_condition?: string;
}

export interface ValidationUX {
  title: string;
  user_message: string;
  primary_action: ValidationAction;
  secondary_action?: ValidationAction;
  impact: string;
}

export interface ValidationContext {
  item_id?: string;
  item_name?: string;
  field_name?: string;
  raw_value?: string | number;
  expected_value?: string;
  [key: string]: unknown;
}

export interface ValidationEvent {
  id: string;
  error_type: string;
  severity: Severity;
  session_id: string;
  created_at: string;
  context: ValidationContext;
  ux: ValidationUX;
  resolved_at?: string | null;
  acknowledged?: boolean;
  justification?: string;
}

export interface TelemetryPayload {
  event:
    | "validation_triggered"
    | "warning_acknowledged"
    | "block_resolved"
    | "justification_submitted";
  session_id: string;
  error_type: string;
  severity?: Severity;
  resolution_time_ms?: number;
  clicks_to_fix?: number;
  justification_length?: number;
}
