import axios from "axios";
import { API_BASE } from "../apiBase.js";

export function useValidationManager(sessionId) {
  const acknowledgeWarning = async ({ errorType, itemId }) => {
    if (!sessionId || !errorType) return;
    await axios.post(`${API_BASE}/sessions/${encodeURIComponent(sessionId)}/validation-events/ack`, {
      error_type: errorType,
      item_id: itemId || null,
    });
  };

  const submitJustification = async ({ actionId, reason, itemId, errorType }) => {
    if (!sessionId || !actionId || !reason) return;
    await axios.post(
      `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/validation-events/justify`,
      {
        action_id: actionId,
        reason,
        item_id: itemId || null,
        error_type: errorType || null,
      }
    );
  };

  const trackValidationEvent = async (payload) => {
    if (!sessionId || !payload?.event || !payload?.error_type) return;
    await axios.post(
      `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/validation-telemetry`,
      payload
    );
  };

  return {
    acknowledgeWarning,
    submitJustification,
    trackValidationEvent,
  };
}

