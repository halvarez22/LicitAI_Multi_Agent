import React from 'react';
import { Loader2 } from 'lucide-react';
import {
    GENERATION_STREAM_PANELS,
    jobsForStreamPanel,
    shouldShowDualStreamPanels,
    streamPanelModeLabel,
} from '../generationStreamUi.js';
import {
    generationJobStatusLabelEs,
    generationJobStatusStyle,
    generationModeLabelEs,
    generationStageLabelEs,
} from '../generationModeUi.js';

/**
 * Lista compacta de jobs de un stream.
 * @param {{ jobs: Array<Record<string, unknown>>, emptyHint?: string }} props
 */
function StreamJobList({ jobs, emptyHint }) {
    if (!Array.isArray(jobs) || jobs.length === 0) {
        return emptyHint ? (
            <p style={{ margin: 0, fontSize: '10px', color: 'rgba(148,163,184,0.85)', lineHeight: 1.45 }}>
                {emptyHint}
            </p>
        ) : null;
    }
    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
            {jobs.map((job) => {
                if (!job || typeof job !== 'object') return null;
                const id = String(job.id || '');
                const status = String(job.status || 'pending');
                const style = generationJobStatusStyle(status);
                return (
                    <div
                        key={id}
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            gap: '8px',
                            fontSize: '11px',
                        }}
                    >
                        <span style={{ color: 'rgba(226,232,240,0.85)' }}>{generationStageLabelEs(id)}</span>
                        <span
                            style={{
                                fontSize: '10px',
                                fontWeight: 700,
                                padding: '2px 8px',
                                borderRadius: '999px',
                                background: style.bg,
                                color: style.color,
                                border: `1px solid ${style.border}`,
                                whiteSpace: 'nowrap',
                            }}
                        >
                            {generationJobStatusLabelEs(status)}
                        </span>
                    </div>
                );
            })}
        </div>
    );
}

/**
 * Panel compacto de cola `generation_state` (F3.2 + F7 dual-stream).
 * @param {{
 *   generationState: Record<string, unknown>|null,
 *   streamRuns?: Record<string, { active?: boolean }>|null,
 *   activeMode?: string|null,
 * }} props
 */
const GenerationQueuePanel = ({ generationState, streamRuns = null, activeMode = null }) => {
    const jobs = generationState?.jobs;
    const dual = shouldShowDualStreamPanels(generationState);

    if (dual) {
        const panels = GENERATION_STREAM_PANELS.map((panel) => ({
            ...panel,
            jobs: jobsForStreamPanel(generationState, panel.id),
            modeLabel: streamPanelModeLabel(generationState, panel.id),
            active: Boolean(streamRuns?.[panel.id]?.active),
        })).filter((p) => p.jobs.length > 0 || p.active);

        if (panels.length === 0) return null;

        return (
            <div style={{ marginTop: '8px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {panels.map((panel) => (
                    <div
                        key={panel.id}
                        style={{
                            padding: '10px 12px',
                            borderRadius: '10px',
                            background: 'rgba(15,23,42,0.55)',
                            border: panel.active
                                ? '1px solid rgba(99,102,241,0.45)'
                                : '1px solid rgba(255,255,255,0.06)',
                        }}
                    >
                        <div
                            style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '8px',
                                marginBottom: '8px',
                                fontSize: '10px',
                                fontWeight: 800,
                                color: 'rgba(226,232,240,0.75)',
                                textTransform: 'uppercase',
                                letterSpacing: '0.04em',
                            }}
                        >
                            {panel.active ? <Loader2 className="animate-spin" size={12} /> : null}
                            {panel.label}
                            {panel.modeLabel ? (
                                <span
                                    style={{
                                        marginLeft: 'auto',
                                        fontWeight: 700,
                                        color: '#a5b4fc',
                                        textTransform: 'none',
                                    }}
                                >
                                    {panel.modeLabel}
                                </span>
                            ) : null}
                        </div>
                        <StreamJobList
                            jobs={panel.jobs}
                            emptyHint={panel.active ? 'Preparando etapas…' : undefined}
                        />
                    </div>
                ))}
            </div>
        );
    }

    if (!Array.isArray(jobs) || jobs.length === 0) return null;

    const modeLabel = generationState?.generation_mode
        ? generationModeLabelEs(String(generationState.generation_mode))
        : activeMode
          ? generationModeLabelEs(activeMode)
          : null;
    const legacyActive = Boolean(streamRuns?.full?.active)
        || Boolean(streamRuns?.technical?.active)
        || Boolean(streamRuns?.economic?.active);

    return (
        <div
            style={{
                marginTop: '8px',
                padding: '10px 12px',
                borderRadius: '10px',
                background: 'rgba(15,23,42,0.55)',
                border: '1px solid rgba(255,255,255,0.06)',
            }}
        >
            <div
                style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    marginBottom: '8px',
                    fontSize: '10px',
                    fontWeight: 800,
                    color: 'rgba(226,232,240,0.75)',
                    textTransform: 'uppercase',
                    letterSpacing: '0.04em',
                }}
            >
                {legacyActive ? <Loader2 className="animate-spin" size={12} /> : null}
                Cola de generación
                {modeLabel ? (
                    <span style={{ marginLeft: 'auto', fontWeight: 700, color: '#a5b4fc', textTransform: 'none' }}>
                        {modeLabel}
                    </span>
                ) : null}
            </div>
            <StreamJobList jobs={jobs} />
        </div>
    );
};

export default GenerationQueuePanel;
