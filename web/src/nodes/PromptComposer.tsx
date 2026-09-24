import { useDebouncedDraft } from './useDebouncedDraft';
import type {
  ImageGenerationParameters,
  VideoGenerationParameters,
} from '../domain/types';


interface PromptComposerProps {
  kind: 'image' | 'video';
  prompt: string;
  parameters: ImageGenerationParameters | VideoGenerationParameters;
  onPromptChange: (prompt: string) => void;
  onParametersChange: (
    parameters: ImageGenerationParameters | VideoGenerationParameters,
  ) => void;
  onGenerate: (request: {
    prompt: string;
    parameters: ImageGenerationParameters | VideoGenerationParameters;
  }) => void;
  disabled?: boolean;
  /** How many connected notes have text; their text is added in front of this prompt. */
  noteCount?: number;
}


export function PromptComposer({
  kind,
  prompt,
  parameters,
  onPromptChange,
  onParametersChange,
  onGenerate,
  disabled = false,
  noteCount = 0,
}: PromptComposerProps) {
  const imageParameters = parameters as ImageGenerationParameters;
  const videoParameters = parameters as VideoGenerationParameters;
  const testId = `prompt-composer-${kind}`;
  const { draft, setDraft, flush } = useDebouncedDraft(prompt, onPromptChange);

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
      {kind === 'image' ? (
        <div className="prompt-options">
          <label>
            size
            <select
              disabled={disabled}
              aria-label="size"
              value={imageParameters.size}
              onChange={(event) => onParametersChange({ ...imageParameters, size: event.target.value as '1K' | '2K' })}
            >
              <option value="1K">1K</option>
              <option value="2K">2K</option>
            </select>
          </label>
          <label>
            aspect ratio
            <select
              disabled={disabled}
              aria-label="aspect-ratio"
              value={imageParameters.aspectRatio}
              onChange={(event) => onParametersChange({ ...imageParameters, aspectRatio: event.target.value })}
            >
              <option value="match_input_image">Match input</option>
              <option value="1:1">1:1</option>
              <option value="16:9">16:9</option>
              <option value="9:16">9:16</option>
              <option value="4:3">4:3</option>
            </select>
          </label>
          <label>
            format
            <select
              disabled={disabled}
              aria-label="output-format"
              value={imageParameters.outputFormat}
              onChange={(event) => onParametersChange({ ...imageParameters, outputFormat: event.target.value as 'png' | 'jpeg' })}
            >
              <option value="png">PNG</option>
              <option value="jpeg">JPEG</option>
            </select>
          </label>
        </div>
      ) : (
        <div className="prompt-options">
          <label>
            duration
            <select
              disabled={disabled}
              aria-label="duration"
              value={videoParameters.duration}
              onChange={(event) => onParametersChange({ ...videoParameters, duration: Number(event.target.value) })}
            >
              <option value={5}>5s</option>
              <option value={10}>10s</option>
            </select>
          </label>
          <label>
            resolution
            <select
              disabled={disabled}
              aria-label="resolution"
              value={videoParameters.resolution}
              onChange={(event) => onParametersChange({ ...videoParameters, resolution: event.target.value as '480p' | '720p' })}
            >
              <option value="480p">480p</option>
              <option value="720p">720p</option>
            </select>
          </label>
          <label>
            aspect ratio
            <select
              disabled={disabled}
              aria-label="aspect-ratio"
              value={videoParameters.aspectRatio}
              onChange={(event) => onParametersChange({ ...videoParameters, aspectRatio: event.target.value })}
            >
              <option value="adaptive">Adaptive</option>
              <option value="16:9">16:9</option>
              <option value="9:16">9:16</option>
              <option value="1:1">1:1</option>
            </select>
          </label>
          <label className="checkbox-option">
            <input
              aria-label="generate-audio"
              type="checkbox"
              disabled={disabled}
              checked={videoParameters.generateAudio}
              onChange={(event) => onParametersChange({ ...videoParameters, generateAudio: event.target.checked })}
            />
            audio
          </label>
        </div>
      )}
      <button
        type="button"
        disabled={disabled}
        onClick={(event) => {
          event.stopPropagation();
          flush();
          onGenerate({ prompt: draft, parameters });
        }}
      >
        生成
      </button>
    </div>
  );
}
