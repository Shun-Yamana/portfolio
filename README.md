＜インフラ設計概要（セキュリティ重視の簡易 API 構成）＞

本構成は、シンプルなアプリケーションを題材に、実運用を想定したセキュアな AWS アーキテクチャ設計を検証する目的で作成している。
機能最小化と攻撃面の縮小を前提に、各レイヤーで責務を明確に分離している。

＜Lambda 設計判断＞

・タイムアウト設定

タイムアウトは 30 秒 に設定

実処理は 5 秒以内に完了する軽量 API を想定

初期化処理・コールドスタート（数百 ms）を考慮しつつ、
無限ループ等の異常系を確実に検知する安全上限として 30 秒を採用

・同時実行数

Lambda 側では明示的な同時実行制限は設定していない

API Gateway 側で ルート単位スロットリング（100 req/s） を設定

アカウントレベルの同時実行数制限により過負荷は抑制可能

本格運用時は CloudWatch メトリクスを監視し、必要に応じて制限を追加する方針

・IAM 実行ロール（最小権限）

CloudWatch Logs 出力に必要な 最小権限のみ付与

信頼ポリシーに aws:SourceAccount 条件を付与し、同一アカウントからの実行のみ許可

マネージドポリシーは使用せず、インラインポリシーで権限を明示的に定義

不要な権限付与や権限の横展開を防止

＜コード保護・監査＞

Lambda Code Signing を必須化

未署名コードや CI/CD 設定ミスによる不正デプロイを構成レベルで防止

CloudTrail / AWS Config を有効化

環境変数・ログは 専用 KMS キーで暗号化

学習用途としては過剰だが、監査可能性を重視した設計

＜監視＞

CloudWatch アラーム

Errors

Throttles

サイレントフェイルや性能劣化の早期検知を目的

＜API Gateway 設計判断＞
・API タイプ選定

HTTP API を採用

REST API と比較して低コスト

機能を最小化し攻撃面を縮小

認証や複雑な変換が不要なため、**「必要十分な API」**として選定

API Gateway → Lambda 権限制御

Lambda リソースベースポリシーを使用

API Gateway サービスプリンシパルのみ Invoke を許可

SourceArn は全ルートキャッチ（デバッグ・検証用途を考慮）

利点

IAM ロール管理の簡素化

権限の責務が Lambda 側に集約され、意図が明確

CloudFormation 管理が単純

＜改善余地＞

本番環境では v1/* など特定ルートに絞り込み可能

ルート設計

明示的に定義したルートのみ公開

GET /health

GET /status

$default（想定外パスの可視化用）

効果

想定外リクエストのログ取得

ルーティング制御は最小限にし、検証ロジックを Lambda 側に集約

＜CloudFront 設計判断＞
役割定義

API Gateway 前段の セキュアなエッジとして利用

Lambda@Edge 等は使用せず、責務を限定

通信・証明書

HTTPS のみ許可（HTTP → HTTPS リダイレクト）

TLS 最低バージョン：TLSv1.2_2021

ACM（SNI）証明書を利用し、運用負荷を抑制

オリジン設計

オリジンは API Gateway HTTP API のみ

CloudFront ドメインのみを公開し、API Gateway の構造を隠蔽

キャッシュ方針

動的エンドポイント前提のため TTL 最小（実質キャッシュなし）

正確性・安全性を優先

セキュリティヘッダー

HSTS（1 年、Subdomain 含む、Preload）

X-Content-Type-Options

X-Frame-Options

ブラウザレベルでの攻撃面を縮小

アクセス制御（将来対応）

＜現状は未実装（設計余地として明示）＞

将来的に CloudFront → API Gateway 間のカスタムヘッダー検証や WAF 統合を想定

監視・運用拡張

CloudFront / API Gateway / Lambda メトリクス監視

SNS 通知（本番時に有効化可能）

AWS Security Hub / GuardDuty 連携を想定

インシデント対応・運用フェーズを見据えた設計

将来拡張

RDS / DynamoDB 連携

Lambda の VPC 接続を含む最小権限設計検証

ステートフル処理・業務データ管理への対応
