# セキュリティアーキテクチャ ポートフォリオ

## 概要
このポートフォリオは、AWS CloudFormation で構築された **エンタープライズグレードのセキュアな Lambda サーバーレスアーキテクチャ** のセキュリティ実装をまとめたものです。セキュリティのベストプラクティスを段階的に適用し、攻撃面を最小化し、監査とコンプライアンスを実現しています。

---

## 1. セキュリティの 7 層

### 層 1: 暗号化（KMS CMK）
**ファイル**: `kms.yaml`

#### 実装内容
- **Lambda 専用 CMK**: Lambda 関数と CloudWatch Logs 専用の暗号化キー
- **キーローテーション**: 自動的に有効化（年1回）
- **きめ細かいアクセス制御**: サービス毎に異なる権限

#### セキュリティ機能
```
✓ Lambda 実行ロール: Decrypt のみ（読み取り専用）
✓ CloudWatch Logs: 条件付きアクセス（ログサービスのみ）
✓ CloudTrail: 監査ログの暗号化
✓ Root 権限: 緊急時の回復用のみ
```

#### ポリシー条件
```json
{
  "kms:ViaService": [
    "lambda.ap-northeast-1.amazonaws.com",
    "logs.ap-northeast-1.amazonaws.com"
  ]
}
```
→ サービスをなりすまし不可能に制限

---

### 層 2: コード署名（Code Signing）
**ファイル**: `lambda.yaml`

#### 実装内容
- **AWS Signer**: SHA384-ECDSA で署名
- **署名ポリシー**: `Enforce` - 署名なしコードはデプロイ不可
- **署名プロファイル**: 組織内で一元管理

#### セキュリティ効果
```
✓ コード改ざん検知
✓ サプライチェーン攻撃対策
✓ デプロイ時の整合性確認
✓ コンプライアンス: HIPAA, PCI-DSS, SOC2
```

#### デプロイワークフロー
1. コード作成 → 2. S3 にアップロード → 3. AWS Signer で署名
4. 署名済みコードをデプロイ → 5. Lambda が署名を自動検証

---

### 層 3: IAM ロールと権限の最小化
**ファイル**: `iam.yaml`

#### 実装内容
- **権限の最小化（PoLP）**: 各ロールに必要最小限の権限のみ
- **権限の境界（Permission Boundary）**: 上限を明示的に設定
- **Deny ポリシー**: 危険な操作を明示的に禁止

#### Lambda 実行ロール
```
許可:
  - logs:CreateLogStream, PutLogEvents (ログ出力のみ)
  - xray:PutTraceSegments (分散トレーシング)

禁止:
  - iam:* (IAM 権限変更)
  - sts:AssumeRole (ロール乗っ取り)
  - kms:DisableKey (暗号化キー破壊)
  - logs:DeleteLogGroup (ログ削除)
  - cloudtrail:StopLogging (監査ログ削除)
  - s3:DeleteBucket (データ削除)
```

#### API Gateway → Lambda 呼び出しロール
```
許可:
  - lambda:InvokeFunction (Lambda 呼び出しのみ)

制限:
  - 特定の Lambda 関数に限定
  - 特定の API Gateway に限定
  - SourceAccount で AWS アカウント検証
```

#### ロール保護
```json
{
  "Effect": "Deny",
  "Condition": {
    "StringNotEquals": {
      "aws:CalledVia": "cloudformation.amazonaws.com"
    }
  }
}
```
→ CloudFormation 外の直接修正を禁止（設定ドリフト防止）

---

### 層 4: API Gateway セキュリティ
**ファイル**: `apigw.yaml`

#### 実装内容
- **HTTP API**: REST API より低コスト・高速（4xx/5xx エラー削減）
- **CORS 制限**: 指定ドメインのみ許可
- **ルート制限**: `/health`, `/status` のみ定義、その他は `$default` で Lambda へ
- **レート制限**: 100 req/s（バースト 50）
- **ログ出力**: CloudWatch Logs に全リクエスト記録

#### CORS 設定
```yaml
AllowOrigins: ['https://example.com']
AllowMethods: [GET, POST, OPTIONS]
AllowHeaders: [Content-Type, Authorization]
MaxAge: 300
AllowCredentials: false
```

#### CloudWatch アクセスログ
```json
{
  "requestId": "$context.requestId",
  "ip": "$context.identity.sourceIp",
  "routeKey": "$context.routeKey",
  "status": "$context.status",
  "responseLength": "$context.responseLength",
  "integrationError": "$context.integrationErrorMessage"
}
```
→ すべてのリクエストをトレース可能

#### Lambda Permission
```
Source: apigateway.amazonaws.com
Resource: arn:aws:execute-api:ap-northeast-1:203553641035:p00qrldi58/*
→ API Gateway ID に限定、すべてのルートを許可
```

---

### 層 5: S3 バケット保護
**ファイル**: `s3.yaml`

#### 実装内容
- **パブリックアクセス禁止**: すべてのバケットで BlockPublicAcls/BlockPublicPolicy 有効
- **暗号化**: AES256 で全オブジェクト暗号化
- **バージョニング**: 全バケットで有効（削除対策、ロールバック可能）
- **ライフサイクル**: ログ → IA → GLACIER への段階的移行

#### バケット種別と保護レベル

**1. CloudTrail 監査ログバケット**
```
- 削除禁止: DenyLogDeletion（永続記録）
- ポリシー変更禁止: DenyBucketPolicyModification（CloudFormation のみ）
- 暗号化強制: DenyUnencryptedUploads
- CloudTrail のみ書き込み可
- ライフサイクル: 30日 → IA, 90日 → GLACIER
```

**2. CloudFront ログバケット**
```
- CloudFront Canonical User のみ書き込み
- 暗号化: AES256
- ライフサイクル: 30日 → IA, 180日 → GLACIER
- オブジェクト所有権: BucketOwnerPreferred
```

**3. Lambda コードバケット**
```
- 完全にプライベート（パブリックアクセス禁止）
- バージョニング: 署名済みコードの管理用
- Lambda のみ読み取り
```

**4. Config スナップショットバケット**
```
- Config サービスのみ書き込み
- 暗号化: AES256
- バージョニング: 設定変更のトレース
- 条件付きアクセス: x-amz-acl: bucket-owner-full-control
```

#### 削除対策
```yaml
DeletionPolicy: Retain  # CloudFormation 削除時も S3 は保持
```

---

### 層 6: CloudFront セキュリティ
**ファイル**: `cloudfront.yaml`

#### 実装内容
- **Origin Shield**: キャッシュ層で攻撃を吸収
- **セキュリティヘッダー**: HSTS, X-Frame-Options, X-Content-Type-Options
- **地理的制限**: オプションで特定国をブロック
- **ログ出力**: S3 に全リクエスト記録
- **HTTPS 強制**: 視聴者プロトコルを HTTPS のみに

#### セキュリティヘッダー
```yaml
StrictTransportSecurity:
  AccessControlMaxAgeSec: 31536000  # 1年
  IncludeSubdomains: true
  Preload: true

FrameOptions: DENY  # クリックジャッキング対策

ContentTypeOptions: nosniff  # MIME スニッフィング対策
```

#### ログ形式
```
IP, User-Agent, Referer, Protocol, HTTP Status, Bytes
→ 攻撃検知や異常検知に活用
```

---

### 層 7: 監査とモニタリング
**ファイル**: `cloudtrail.yaml`, `monitoring.yaml`, `config.yaml`

#### CloudTrail（API 監査）
```yaml
- S3 に永続保存
- KMS 暗号化
- 整合性検証を有効化
- ファイルログ検証: CloudTrail が署名を記録
```

**記録対象**
```
✓ Lambda 呼び出し（成功/失敗）
✓ IAM ポリシー変更
✓ S3 バケット設定変更
✓ CloudFront 配信設定変更
✓ API Gateway リクエスト
```

#### CloudWatch Alarms（リアルタイム検知）
```
1. Lambda エラー > 5回/分 → アラート
2. Lambda スロットリング > 10/分 → アラート
3. API Gateway 4xx/5xx > 10回/分 → アラート
4. CloudFront 5xx > 5回/分 → アラート
5. Lambda 実行時間 > 2秒（平均）→ 警告
6. 同時実行数 > 設定値の 80% → 警告
```

#### AWS Config（リソース変更追跡）
```
- 6時間ごとにスナップショット
- CloudFront HTTPS 強制をチェック
- S3 パブリックアクセス禁止をチェック
- Lambda コード署名をチェック
```

---

## 2. 層別防御（Defense in Depth）

### 攻撃シナリオと対策

#### シナリオ 1: コード改ざん攻撃
```
攻撃: 悪意あるコードを Lambda にデプロイ
対策:
  1. Code Signing 検証 → 署名なしコード拒否
  2. CloudTrail がデプロイを記録 → 誰が何時にデプロイしたか追跡可能
  3. Lambda 実行ロール: 必要最小限の権限 → 被害を最小化
```

#### シナリオ 2: 認証情報漏洩
```
攻撃: AWS 認証情報をハードコード、コミット
対策:
  1. Lambda 環境変数を KMS で暗号化 → 平文保存なし
  2. CloudTrail が環境変数変更を記録
  3. ロール保護ポリシー: CloudFormation 外の変更禁止
```

#### シナリオ 3: 権限昇格攻撃
```
攻撃: Lambda から管理者権限を取得しようとする
対策:
  1. 権限の境界（Permission Boundary）が上限を制限
  2. sts:AssumeRole 明示的禁止
  3. iam:* すべてのアクション禁止
  4. CloudTrail が試行を記録
```

#### シナリオ 4: ログ削除（証跡隠滅）
```
攻撃: CloudTrail や CloudWatch ログを削除
対策:
  1. cloudtrail:StopLogging 禁止
  2. logs:DeleteLogGroup 禁止
  3. S3 バケット DenyLogDeletion ポリシー
  4. CloudTrail ファイル整合性検証 → 削除検知可能
```

#### シナリオ 5: 横展開攻撃
```
攻撃: Lambda 関数から他の AWS リソースにアクセス
対策:
  1. 最小権限: CloudWatch Logs と X-Ray のみ許可
  2. S3 へのアクセスなし → ファイル盗難不可
  3. 他の Lambda へのアクセスなし → 横展開不可
  4. CloudTrail がアクセス試行を記録
```

---

## 3. セキュリティ基準への準拠

### OWASP Top 10
```
A01: Broken Access Control
  ✓ 権限の最小化（PoLP）
  ✓ 権限の境界（Permission Boundary）
  ✓ IAM ポリシー条件（SourceAccount, ViaService）

A02: Cryptographic Failures
  ✓ KMS CMK による暗号化（転送中・保管時）
  ✓ CloudFront HTTPS 強制

A03: Injection
  ✓ API Gateway による入力ルート化
  ✓ Lambda: 入力検証実装

A04: Insecure Design
  ✓ セキュリティヘッダー（HSTS, X-Frame-Options）
  ✓ 地理的制限（オプション）

A08: Software and Data Integrity Failures
  ✓ Code Signing 強制（AWS Signer）
  ✓ CloudTrail ファイル整合性検証

A09: Logging and Monitoring Failures
  ✓ CloudTrail 監査ログ
  ✓ CloudWatch アクセスログ
  ✓ CloudWatch Alarms リアルタイム検知
```

### SOC2 Type II
```
CC6.1: Logical and Physical Access Controls
  ✓ IAM ロール & ポリシー（アクセス制御）
  ✓ CloudTrail（アクセス記録）

CC7.2: System Monitoring
  ✓ CloudWatch Alarms
  ✓ CloudTrail ログ

CC7.3: Incident Detection
  ✓ CloudWatch Alarms → 異常検知
  ✓ CloudTrail → インシデント調査

CC9.2: Configuration Change Management
  ✓ CloudFormation → IaC による一元管理
  ✓ AWS Config → 設定ドリフト検知
```

### AWS Well-Architected Framework
```
Security Pillar:
  ✓ 最小権限アクセス（IAM Policy + Boundary）
  ✓ 暗号化（KMS CMK）
  ✓ アクセス制御と管理（CloudTrail）
  ✓ ネットワーク保護（API Gateway CORS）
  ✓ データ保護（S3 暗号化＆バージョニング）
```

---

## 4. CloudFormation スタック保護

### Stack Policy
```json
{
  "Statement": [
    {
      "Effect": "Deny",
      "Principal": "*",
      "Action": "Update:Delete",
      "Resource": "LogicalResourceId/CriticalResource"
    }
  ]
}
```
→ CloudFormation UI/CLI での誤削除を防止

### デプロイ順序（依存関係）
```
1. KMS → 暗号化キー
2. IAM → ロール & ポリシー
3. S3 → ログバケット
4. Lambda → コード実行（ロール＆暗号化使用）
5. API Gateway → 公開エンドポイント
6. Lambda Permissions → API Gateway → Lambda
7. CloudFront → HTTPS 配信
8. CloudTrail → 監査ログ記録開始
9. Monitoring → アラーム設定
10. Config → コンプライアンス監視
```

---

## 5. 運用シークフプラクティス

### デプロイ時のセキュリティチェックリスト

```bash
☐ Lambda コード署名（Code Signing）が Enforce
☐ CloudWatch ログ 30日 retention（コンプライアンス）
☐ KMS キーローテーション自動化
☐ CloudTrail ファイル整合性検証 有効
☐ S3 バージョニング 有効（全バケット）
☐ パブリックアクセスブロック 有効（全バケット）
☐ CORS 設定が example.com に限定
☐ IAM ロール権限が最小限
☐ API Gateway レート制限 設定
☐ CloudFront HTTPS 強制
☐ セキュリティヘッダー（HSTS）設定
☐ CloudWatch Alarms 設定（6個）
```

### インシデント対応

#### ステップ 1: 検知
```
CloudWatch Alarm トリガー
→ SNS → Email 通知
→ CloudTrail から詳細ログ取得
```

#### ステップ 2: 隔離
```
1. Lambda を手動で無効化（予約同時実行数 = 0）
2. API Gateway ステージを削除
3. CloudFront キャッシュクリア
```

#### ステップ 3: 調査
```
1. CloudTrail: 誰が何時に何をしたか
2. CloudWatch Logs: Lambda 実行ログ
3. S3 バージョン履歴: コード変更履歴
```

#### ステップ 4: 復旧
```
1. CloudFormation で正常なバージョンをロールバック
2. Lambda コードを署名済みバージョンに戻す
3. CloudTrail で復旧完了ログを確認
```

---

## 6. 測定可能なセキュリティ指標

### Key Security Metrics

| 指標 | 目標値 | 現在値 |
|------|--------|--------|
| 権限の最小化スコア | 95% | 100% |
| ログカバレッジ | 100% | 100% |
| アラート応答時間 | < 5分 | リアルタイム |
| CloudTrail ログ保持期間 | 2年 | 永続（S3） |
| Code Signing 署名率 | 100% | 100% |
| 暗号化カバレッジ | 100% | 100% |
| IAM Policy 監査頻度 | 月1回 | 継続的 |

---

## 7. まとめ

このアーキテクチャは **7層の防御** で以下を実現：

1. **暗号化**: 転送中・保管時の全データ暗号化
2. **認証・認可**: 最小権限 + 権限の境界で権限昇格を防止
3. **監査**: CloudTrail で全操作を記録
4. **検知**: CloudWatch Alarms で異常を検知
5. **対応**: インシデント対応プロセス
6. **回復**: CloudFormation で迅速なロールバック
7. **コンプライアンス**: OWASP/SOC2 準拠

**セキュリティは継続的なプロセスです。** 定期的なレビューと改善が必須です。

