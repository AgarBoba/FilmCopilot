import type {
  ImageGenerationParameters,
  VideoGenerationParameters,
} from '../domain/types';


export const getDefaultImageParameters = (): ImageGenerationParameters => ({
  size: '2K',
  aspectRatio: 'match_input_image',
  outputFormat: 'png',
});


export const getDefaultVideoParameters = (): VideoGenerationParameters => ({
  duration: 5,
  resolution: '720p',
  aspectRatio: 'adaptive',
  generateAudio: true,
});
