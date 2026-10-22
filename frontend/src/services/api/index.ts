export {
  api,
  ApiError,
  NetworkError,
  TimeoutError,
  ValidationError,
  type RequestOptions,
} from "./client";

export type {
  ErrorDetail,
  ReadyResponseData,
  StatusResponseData,
  VersionResponseData,
  ResponseMeta,
  CapabilityStatus,
  DependencyHealth,
  UpstreamIntegrationStatus,
  HealthResponseData,
} from "@/schemas/api";
