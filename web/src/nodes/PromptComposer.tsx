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
}


export function PromptComposer({
  kind,
  prompt,
  parameters,
  onPromptChange,
  onParametersChange,
  onGenerate,
  disabled = false,
}: PromptComposerProps) {
  const imageParameters = parameters as ImageGenerationParameters;
  const videoParameters = parameters as VideoGenerationParameters;
  const testId = `prompt-composer-${kind}`;

  return (
    <div className="prompt-composer" data-testid={testId}>
      <textarea
        aria-label="Prompt"
        value={prompt}
        placeholder="描述你想生成的画面…"
        onChange={(event) => onPromptChange(event.target.value)}
        onMouseDown={(event) => event.stopPropagation()}
      />
      {kind === 'image' ? (
        <div className="prompt-options">
          <label>
            size
            <select
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
          onGenerate({ prompt, parameters });
        }}
      >
        生成
      </button>
    </div>
  );
}
