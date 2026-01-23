Lambda 設計判断（lambda.yaml）
タイムアウト設定

Lambda のタイムアウトは 30 秒 に設定している。

初期化処理やコールドスタート（約 270ms）時間を考慮し、
安定した運用に必要な十分なマージンを確保している。

本構成では 5 秒以内に完了する軽量な処理を想定しているため、
30 秒は異常系（無限ループ）を検出するための安全な上限として機能している。

同時実行数制限

同時実行数は 制限を設定していない（無制限）。

HTTP API は アカウントレベルの同時実行数制限（デフォルト 1000）により保護されている。

API Gateway 側で ルート単位の スロットリング（100 req/s）を実装しているため、
Lambda 側での明示的な制限は不要と判断した。

ただし 本格運用時は CloudWatch メトリクスで監視し、
必要に応じて制限を追加する。

IAM 実行ロール設計

Lambda 実行ロールは CloudWatch Logs 出力に必要な最小権限のみを付与している。

LambdaExecutionRole:
  Type: AWS::IAM::Role
  Properties:
    RoleName: !Sub ${FunctionName}-execution-role
    AssumeRolePolicyDocument:
      Version: '2012-10-17'
      Statement:
        - Effect: Allow
          Principal:
            Service: lambda.amazonaws.com
          Action: 'sts:AssumeRole'
          Condition:
            StringEquals:
              aws:SourceAccount: !Ref AWS::AccountId


aws:SourceAccount 条件を付与し、同一アカウントからの実行のみ許可

権限は インラインポリシーで個別定義し、汎用マネージドポリシーは使用していない

これにより 不要な権限付与や権限の横展開を防止している。

データ保護・監査

CloudTrail + AWS Config を有効化

Lambda 環境変数および関連ログは 専用 KMS キーで暗号化

設定変更や API 操作を 後から追跡・説明可能な構成とするため、
学習用途としては過剰だが 監査を前提とした設計を採用している。

Code Signing 強制

Lambda には Code Signing を必須としている。

意図しないコード差し替え

CI/CD 設定ミスによる未検証コードのデプロイ

これらを 構成レベルで防止するため、
署名されていないコードは実行されない設計とした。

監視・アラート

以下の CloudWatch アラームを設定している。

Errors

Throttles

障害の兆候を 早期に検知し、
サイレントフェイルや性能劣化を見逃さないことを目的としている。






API Gateway 設計判断（apigateway.yaml）
API タイプ選定（HTTP API）

API Gateway は HTTP API を採用している。

REST API と比較して 低価格

機能を最小限に抑えることで 攻撃面を縮小

本構成では 認証・高度な変換が不要なため、過剰機能を避けた

セキュリティとコストのバランスを考慮し、
**「必要十分な API」**として HTTP API を選定した。

API Gateway → Lambda IAM ロール

API Gateway から Lambda を呼び出すため、**Lambda リソースベースのポリシー** を採用している。

実装パターン：
- API Gateway は 認証情報なし で Lambda を直接呼び出し
- Lambda::Permission で API Gateway サービスプリンシパルのみを許可
- SourceArn をワイルドカード（*/）で指定し、全ルートをキャッチ

```yaml
LambdaApiGatewayInvokePermissionCatchAll:
  Type: AWS::Lambda::Permission
  Properties:
    FunctionName: !Ref SecureLambdaFunction
    Action: lambda:InvokeFunction
    Principal: apigateway.amazonaws.com
    SourceArn: !Sub 'arn:aws:execute-api:${AWS::Region}:${AWS::AccountId}:${HttpApiId}/*'
```

利点：
- IAM ロール管理の複雑さを軽減
- 権限の意図が明確（Lambda 側で許可を定義）
- CloudFormation での管理が単純化

改善余地：
- 本格運用時は SourceArn を特定ルート（例：v1/*）に絞り込み可能

ルート制限（攻撃面縮小）

公開ルートは 明示的に定義したもののみとしている。

```yaml
# GET /health
RouteKey: 'GET /health'

# GET /status
RouteKey: 'GET /status'

# Catch-all for unexpected paths
RouteKey: '$default'
```

これにより：

- 想定外パスへのアクセスも記録可能（可視化）
- $default ルートで全リクエストが Lambda に到達
- Lambda 側で リクエスト内容を検証・拒否
- API Gateway 側では複雑な制御を行わない（責務の分離）

実装効果：
- 不正アクセスの可視化が容易
- ルート追加時に CloudFront 再デプロイ不要
- セキュリティ検証ロジックをアプリで集約管理




CloudFront 設計判断（cloudfront.yaml）
ディストリビューション種別

CloudFront は 標準ディストリビューションを採用している。

Lambda@Edge や複雑なオリジン分岐は使用せず、
API Gateway の前段としてのセキュアなエッジに役割を限定した。

HTTPS / 証明書設定

HTTPS のみ許可

HTTP アクセスは HTTPS へ強制リダイレクト

TLS 最低バージョン：TLSv1.2_2021

カスタムドメイン利用時は **ACM 証明書（SNI）**を使用

SNI を用いることで 証明書管理を簡素化しつつ、
セキュリティレベルを維持している。

オリジン設計（API Gateway）

オリジンは API Gateway HTTP API のみとし、
CloudFront からは統合エンドポイント経由でアクセスしている。

実装：
- API Gateway: HTTP API（ステージ v1 統合）
- CloudFront OriginPath: 設定せず（API Gateway リージョンエンドポイント直接使用）

ビューア側の URL は CloudFront ドメインのみを公開し、
API Gateway の エンドポイント構造は隠蔽されている。

キャッシュ制御

本構成では CloudFront マネージドキャッシュポリシーを使用している。

デフォルト動作：
- TTL = 0（キャッシュなし）に近い短期キャッシュ
- Cookie / Query String により キャッシュキーを分割
- 動的なヘッダー（Cache-Control）で上書き可能

理由：
- 本構成は動的な健康チェックエンドポイント主用途
- キャッシュ不整合リスク < 正確性・安全性の優先
- CloudFront の標準ポリシーで必要十分な制御が可能

レスポンスヘッダー（セキュリティ）

Response Headers Policy を用いて以下を付与している。

```yaml
StrictTransportSecurity:
  AccessControlMaxAgeSec: 31536000  # 1年間 HTTPS強制
  IncludeSubdomains: true
  Preload: true

ContentTypeOptions: DENY          # MIME タイプ嗅ぎを防止
FrameOptions: DENY                # Clickjacking 防止
```

現在実装分：
- HSTS: ブラウザの HTTP ダウングレード自動防止
- X-Content-Type-Options: MIME-Sniffing 攻撃防止  
- X-Frame-Options: Clickjacking / UI Redressing 防止

今後の追加候補：
- Referrer-Policy: Referer ヘッダー制御（オプション）

これらにより ブラウザレベルでの攻撃面を縮小している。

カスタムヘッダーによるアクセス制限

**現在：未実装**（オプション機能）

設計段階では CloudFront → API Gateway 間に カスタムヘッダーを付与する予定だったが、
以下の理由から優先度を下げた：

- Lambda Permission で API Gateway 限定のため、追加制限は redundant
- WAF 統合で より柔軟なオリジン制限が可能
- 運用初期段階では シンプルな設計を優先

本格運用時に以下の実装を検討：
```yaml
OriginCustomHeaders:
  - HeaderName: X-Origin-Verification
    HeaderValue: <SecretToken>
```

API Gateway → Lambda 間でヘッダー検証を実装することで、
CloudFront 経由以外の直接アクセスを拒否可能。

オリジン通信のセキュリティ

CloudFront → API Gateway 間も HTTPS のみ

TLSv1.2 を強制

Keepalive / Timeout を明示設定

ネットワーク境界を跨ぐ通信も 暗号化を前提としている。

ログ・監査

CloudFront 標準ログ（S3）

CloudWatch メトリクス

CloudTrail / AWS Config 有効化

誰が・いつ・どこにアクセスしたかを
後から説明できる構成としている。

APIGateway へのアクセス制限

現在の設計：
- Lambda Permission で API Gateway サービスプリンシパル限定
- 言語的には CloudFront 経由が前提だが、API Gateway の SourceArn ワイルドカード設定により
  直接呼び出しも可能（意図的な設計、デバッグ用途）

セキュリティレイヤー：
1. **Lambda Permission**: API GW サービスのみ許可（リソースベース）
2. **CloudFront Origin Shield**: エッジでのキャッシュ + 接続最適化（オプション）
3. **WAF Integration**: IP レート制限・Geo ブロック・マネージドルール（未実装、本格運用時推奨）

今後の改善：
- WAFv2 WebACL で DDoS 対策・IP 制限を実装
- SourceArn を v1/* に絞り込み（すべてのルート許可から特定ルート限定へ）

IPv6 / コスト制御

IPv6 有効化

PriceClass_100 を使用し、コストを制御

グローバル配信よりも
日本向けトラフィックを想定した現実的な設定。

Geo 制限（オプション）

国単位でのアクセス制限を オプションとして実装。

通常時は無効

インシデント対応時に有効化可能




今後の拡張予定（Planned Enhancements）
1. SNS によるアラーム通知

**実装済み**（デフォルト無効、オプション有効化可能）

monitoring.yaml で SNS 統合を実装：
```yaml
EnableSnsNotifications: false  # 本番時は true に設定
SnsEmailAddress: ''            # 本番時は通知先メール指定
```

監視対象：
- Lambda: Errors >= 5/min, Throttles >= 10/min, Duration > 2s, Concurrency >= 80%
- API Gateway: 4xx/5xx エラー >= 10/min
- CloudFront: 5xx エラー >= 5/min
- Composite Alarm: いずれかが ALARM 状態

デプロイ方法：
```bash
aws cloudformation deploy --stack-name monitoring-stack ... \
  --parameter-overrides EnableSnsNotifications=true SnsEmailAddress=your-email@example.com
```

2. AWS Security Hub 連携

AWS Config / CloudTrail / GuardDuty と統合

セキュリティベストプラクティスの継続的評価

検知結果を一元管理し、
運用フェーズを意識したセキュリティ設計へ拡張

3. データベース連携

Lambda から RDS / DynamoDB への接続を想定

IAMロール・VPC接続・セキュリティグループを含めた
最小権限設計の検証

将来的な ステートフル処理・業務データ管理への対応