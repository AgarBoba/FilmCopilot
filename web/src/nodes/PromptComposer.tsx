import { useDebouncedDraft } from './useDebouncedDraft';
import {
  modelForNode,
  modelsOfKind,
  parameterLabelId,
  resolveParameters,
  useModelStore,
  type ModelParameter,
} from '../models/modelStore';

type Parameters = Record<string, unknown>;

interface PromptComposerProps {
  kind: 'image' | 'video';
  prompt: string;
  /** The node's model id; missing means the default model for this kind. */
  modelId?: string | null;
  parameters?: object;
  onPromptChange: (prompt: string) => void;
  onParametersChange: (parameters: Parameters) => void;
  /** Switching model also resets parameters that the new model doesn't have. */
  onModelChange?: (modelId: string, parameters: Parameters) => void;
  onGenerate: (request: { prompt: string; parameters: Parameters; model?: string }) => void;
  disabled?: boolean;
  /** How many connected notes have text; their text is added in front of this prompt. */
  noteCount?: number;
}


/**
 * Prompt box plus the chosen model and its parameters. The controls come from the model's
 * definition (models/*.json via /api/models), so a newly added model needs no UI work.
 */
export function PromptComposer({
  kind,
  prompt,
  modelId,
  parameters,
  onPromptChange,
  onParametersChange,
  onModelChange,
  onGenerate,
  disabled = false,
  noteCount = 0,
}: PromptComposerProps) {
  const models = useModelStore((state) => state.models);
  const choices = modelsOfKind(models, kind);
  const model = modelForNode(models, kind, modelId);
  const values = resolveParameters(model, parameters as Parameters | undefined);
  const testId = `prompt-composer-${kind}`;
  const { draft, setDraft, flush } = useDebouncedDraft(prompt, onPromptChange);
  const setValue = (key: string, value: unknown) => onParametersChange({ ...values, [key]: value });

  return (
    <div className={`prompt-composer nodrag ${disabled ? 'is-locked' : ''}`} data-testid={testId}>
      <textarea
        className="nodrag nowheel"
        aria-label="Prompt"
        value={draft}
        placeholder={noteCount ? '可以留空，会使用上游便签的文字' : '描述你想生成的画面…'}
        readOnly={disabled}
        aria-readonly={disabled}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={flush}
        onMouseDown={(event) => event.stopPropagation()}
      />
      {disabled && (
        <p className="prompt-lock-hint">生成中，完成后才能修改提示词和参数</p>
      )}
      {noteCount > 0 && (
        <p className="prompt-note-hint">
          上游 {noteCount} 条便签的文字会放在这段提示词前面，一起发给模型
        </p>
      )}
      <div className="prompt-options">
        <label className="prompt-model">
          model
          {/* Only one model of this kind: still show its name, just without the menu arrow. */}
          <select
            className={choices.length < 2 ? 'is-single' : undefined}
            disabled={disabled || choices.length < 2}
            aria-label="model"
            value={model?.id ?? ''}
            onChange={(event) => {
              const next = modelForNode(models, kind, event.target.value);
              if (next) onModelChange?.(next.id, resolveParameters(next, values));
            }}
          >
            {choices.map((choice) => <option key={choice.id} value={choice.id}>{choice.label}</option>)}
          </select>
        </label>
        {model?.parameters.map((parameter) => (
          <ParameterControl
            key={`${model.id}-${parameter.key}`}
            parameter={parameter}
            value={values[parameter.key]}
            disabled={disabled}
            onChange={(value) => setValue(parameter.key, value)}
          />
        ))}
      </div>
      {model && model.providerReady === false && (
        <p className="prompt-missing-key">
          还没有 {model.provider} 的对接代码，这个模型暂时不能生成：让你的 Agent 按项目里的 AGENTS.md 接入。
        </p>
      )}
      {model && model.providerReady !== false && model.missingEnv.length > 0 && (
        <p className="prompt-missing-key">
          这个模型还缺 {model.missingEnv.join('、')}，生成会失败：让你的 Agent 按项目里的 AGENTS.md 帮你填好。
        </p>
      )}
      <button
        type="button"
        disabled={disabled}
        onClick={(event) => {
          event.stopPropagation();
          flush();
          onGenerate({ prompt: draft, parameters: values, model: model?.id });
        }}
      >
        生成
      </button>
    </div>
  );
}


function ParameterControl({ parameter, value, disabled, onChange }: {
  parameter: ModelParameter;
  value: unknown;
  disabled: boolean;
  onChange: (value: unknown) => void;
}) {
  const id = parameterLabelId(parameter.key);
  if (parameter.type === 'boolean') {
    return (
      <label className="checkbox-option">
        <input aria-label={id} type="checkbox" disabled={disabled} checked={Boolean(value)}
          onChange={(event) => onChange(event.target.checked)} />
        {parameter.label}
      </label>
    );
  }
  if (parameter.type === 'enum') {
    const options = parameter.options ?? [];
    const index = options.findIndex((option) => option.value === value);
    return (
      <label>
        {parameter.label}
        <select disabled={disabled} aria-label={id} value={String(index)}
          onChange={(event) => onChange(options[Number(event.target.value)]?.value)}>
          {options.map((option, position) => <option key={String(option.value)} value={String(position)}>{option.label}</option>)}
        </select>
      </label>
    );
  }
  if (parameter.type === 'integer' || parameter.type === 'number') {
    return (
      <label>
        {parameter.label}
        <input type="number" aria-label={id} disabled={disabled} value={typeof value === 'number' ? value : ''}
          min={parameter.min} max={parameter.max} step={parameter.type === 'integer' ? 1 : 'any'}
          onChange={(event) => {
            const number = Number(event.target.value);
            if (event.target.value !== '' && !Number.isNaN(number)) onChange(number);
          }} />
      </label>
    );
  }
  return (
    <label>
      {parameter.label}
      <input type="text" aria-label={id} disabled={disabled} value={String(value ?? '')}
        onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}
