# デプロイ手順書

## 前提条件
- AWS CLI 設定済み（リージョン: ap-northeast-1）
- アカウントID: 203553641035
- Python 3.12 Lambda コード（`app/main.py`）準備済み
- **作業ディレクトリ**: `C:\Portfolio\yaml_files`（または `/mnt/c/Portfolio/yaml_files`）

## デプロイ順序

### 1. KMS スタック
Lambda と CloudWatch Logs 用の暗号化キーを作成。

```bash
aws cloudformation deploy \
  --stack-name kms-stack \
  --template-file kms.yaml \
  --capabilities CAPABILITY_IAM \
  --region ap-northeast-1
```

### 2. IAM スタック
Lambda 実行ロール、CloudFront ヘッダー設定用ロールを作成。

```bash
aws cloudformation deploy \
  --stack-name iam-stack \
  --template-file iam.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --region ap-northeast-1
```

### 3. S3 スタック
Lambda コード署名用、CloudTrail ログ用、CloudFront ログ用バケットを作成。

```bash
aws cloudformation deploy \
  --stack-name s3-stack \
  --template-file s3.yaml \
  --region ap-northeast-1
```

### 4. Lambda コード署名

#### 4.1 署名プロファイル作成
```bash
aws signer put-signing-profile \
  --profile-name lambda_code_signing \
  --platform-id "AWSLambda-SHA384-ECDSA" \
  --region ap-northeast-1
```

#### 4.2 Lambda コード圧縮
```bash
cd C:\Portfolio\app
Compress-Archive -Force -Path main.py -DestinationPath ..\app.zip
cd C:\Portfolio
```

#### 4.3 未署名コードを S3 にアップロード
```bash
aws s3 cp /mnt/c/Portfolio/app.zip s3://lambda-code-203553641035-ap-northeast-1/unsigned/app.zip --region ap-northeast-1
```

**PowerShell の場合**:
```powershell
aws s3 cp C:\Portfolio\app.zip s3://lambda-code-203553641035-ap-northeast-1/unsigned/app.zip --region ap-northeast-1
```

#### 4.4 バージョンIDを取得
**Bash/WSL の場合**:
```bash
versionId=$(aws s3api list-object-versions \
  --bucket lambda-code-203553641035-ap-northeast-1 \
  --prefix unsigned/app.zip \
  --query 'Versions[0].VersionId' \
  --output text \
  --region ap-northeast-1)
```

**PowerShell の場合**:
```powershell
$versionId = aws s3api list-object-versions `
  --bucket lambda-code-203553641035-ap-northeast-1 `
  --prefix unsigned/app.zip `
  --query 'Versions[0].VersionId' `
  --output text `
  --region ap-northeast-1
```

#### 4.5 コード署名実行
**Bash/WSL の場合**:
```bash
aws signer start-signing-job \
  --source "s3={bucketName=lambda-code-203553641035-ap-northeast-1,key=unsigned/app.zip,version=$versionId}" \
  --destination "s3={bucketName=lambda-code-203553641035-ap-northeast-1}" \
  --profile-name lambda_code_signing \
  --region ap-northeast-1
```

**PowerShell の場合**:
```powershell
aws signer start-signing-job `
  --source "s3={bucketName=lambda-code-203553641035-ap-northeast-1,key=unsigned/app.zip,version=$versionId}" `
  --destination "s3={bucketName=lambda-code-203553641035-ap-northeast-1}" `
  --profile-name lambda_code_signing `
  --region ap-northeast-1
```

#### 4.6 署名済みファイル確認
```bash
# JOB_ID が分かる場合（推奨: 正確なKeyを取得）
SIGNED_KEY=$(aws signer describe-signing-job \
  --job-id "$JOB_ID" \
  --region ap-northeast-1 \
  --query 'signedObject.s3.key' \
  --output text)

# JOB_ID が不明な場合（直近の成功ジョブから取得）
JOB_ID=${JOB_ID:-$(aws signer list-signing-jobs \
  --status Succeeded \
  --max-results 1 \
  --region ap-northeast-1 \
  --query 'jobs[0].jobId' \
  --output text)}

SIGNED_KEY=${SIGNED_KEY:-$(aws signer describe-signing-job \
  --job-id "$JOB_ID" \
  --region ap-northeast-1 \
  --query 'signedObject.s3.key' \
  --output text)}

# describe-signing-job でキーが空(None)の場合のフォールバック
if [ -z "$SIGNED_KEY" ] || [ "$SIGNED_KEY" = "None" ]; then
  # 既定の配置規約: signed/<JOB_ID>.zip を試す
  CANDIDATE_KEY="signed/${JOB_ID}.zip"
  if aws s3api head-object \
       --bucket lambda-code-203553641035-ap-northeast-1 \
       --key "$CANDIDATE_KEY" \
       --region ap-northeast-1 >/dev/null 2>&1; then
    SIGNED_KEY="$CANDIDATE_KEY"
  else
    # 一覧から該当JobIdを含むキーを検索
    SIGNED_KEY=$(aws s3api list-objects-v2 \
      --bucket lambda-code-203553641035-ap-northeast-1 \
      --prefix signed/ \
      --query "Contents[?contains(Key, '${JOB_ID}')].Key | [-1]" \
      --output text \
      --region ap-northeast-1)
    # signed/ 配下に無い場合、バケット直下も検索（JOB_ID.zip 形式など）
    if [ -z "$SIGNED_KEY" ] || [ "$SIGNED_KEY" = "None" ]; then
      SIGNED_KEY=$(aws s3api list-objects-v2 \
        --bucket lambda-code-203553641035-ap-northeast-1 \
        --query "Contents[?contains(Key, '${JOB_ID}')].Key | [-1]" \
        --output text \
        --region ap-northeast-1)
    fi
  fi
fi

# S3 上にオブジェクトが存在するか事前確認（200 が返ればOK）
aws s3api head-object \
  --bucket lambda-code-203553641035-ap-northeast-1 \
  --key "$SIGNED_KEY" \
  --region ap-northeast-1

# 参考: 一覧で手動確認（キー例の目視用）
aws s3 ls s3://lambda-code-203553641035-ap-northeast-1/signed/ --region ap-northeast-1

echo "SIGNED_KEY=$SIGNED_KEY"
```

**SIGNED_KEY（例: `signed/66fe479e-b653-4326-afa7-c4de1d6a840b.zip`）を使用します。**

### 5. Lambda スタック
署名済みコードを使用して Lambda 関数をデプロイ。

```bash
aws cloudformation deploy \
  --stack-name lambda-stack \
  --template-file lambda.yaml \
  --parameter-overrides \
    CodeS3Key=$SIGNED_KEY \
    KmsStackName=kms-stack \
    IamStackName=iam-stack \
    S3StackName=s3-stack \
    CodeSigningProfileVersionArn=$PROFILE_ARN \
  --capabilities CAPABILITY_IAM \
  --region ap-northeast-1
```

**SignerプロファイルARN取得**:
```bash
aws signer get-signing-profile --profile-name lambda_code_signing --region ap-northeast-1 --query 'profileVersionArn' --output text
```
**NoSuchKey で失敗した場合のリカバリ**:
```bash
# 失敗中のスタックを削除してクリーンに再作成
aws cloudformation delete-stack --stack-name lambda-stack --region ap-northeast-1
aws cloudformation wait stack-delete-complete --stack-name lambda-stack --region ap-northeast-1

# SIGNED_KEY を再確認（上記 4.6 の手順）してから再デプロイ
aws cloudformation deploy \
  --stack-name lambda-stack \
  --template-file lambda.yaml \
  --parameter-overrides \
    CodeS3Key=$SIGNED_KEY \
    KmsStackName=kms-stack \
    IamStackName=iam-stack \
    S3StackName=s3-stack \
    CodeSigningProfileVersionArn=$PROFILE_ARN \
  --capabilities CAPABILITY_IAM \
  --region ap-northeast-1
```

### 6. API Gateway スタック
HTTP API を作成（JWT 認証はオプション）。

```bash
aws cloudformation deploy \
  --stack-name apigw-stack \
  --template-file apigw.yaml \
  --parameter-overrides \
    LambdaStackName=lambda-stack \
    EnableJwtAuth=false \
  --region ap-northeast-1
```

### 7. Lambda Permissions スタック
API Gateway から Lambda を呼び出す権限を付与。

```bash
aws cloudformation deploy \
  --stack-name lambda-permissions-stack \
  --template-file lambda-permissions.yaml \
  --parameter-overrides \
    LambdaStackName=lambda-stack \
    ApiGatewayStackName=apigw-stack \
  --region ap-northeast-1
```

### 8. CloudFront スタック
HTTPS 配信用の CloudFront ディストリビューションを作成。

```bash
aws cloudformation deploy \
  --stack-name cloudfront-stack \
  --template-file cloudfront.yaml \
  --parameter-overrides \
    ApiGatewayStackName=apigw-stack \
    S3StackName=s3-stack \
    EnableWaf=false \
  --region ap-northeast-1
```

### 9. CloudTrail スタック
Lambda API 呼び出しのログ記録を有効化。

```bash
aws cloudformation deploy \
  --stack-name cloudtrail-stack \
  --template-file cloudtrail.yaml \
  --parameter-overrides \
    S3StackName=s3-stack \
  --capabilities CAPABILITY_IAM \
  --region ap-northeast-1
```

### 10. Monitoring スタック
CloudWatch ダッシュボードとアラームを作成。

```bash
aws cloudformation deploy \
  --stack-name monitoring-stack \
  --template-file monitoring.yaml \
  --parameter-overrides \
    LambdaStackName=lambda-stack \
    ApiGatewayStackName=apigw-stack \
    CloudFrontStackName=cloudfront-stack \
    EnableSns=false \
  --region ap-northeast-1
```

### 11. Config スタック（オプション）
AWS Config でリソース変更を記録。

```bash
aws cloudformation deploy \
  --stack-name config-stack \
  --template-file config.yaml \
  --parameter-overrides \
    CloudFrontStackName=cloudfront-stack \
  --capabilities CAPABILITY_IAM \
  --region ap-northeast-1
```

**注意**: Config スタックで Early Validation エラーが発生する場合は、コンソールで手動設定してください（後述）。

## デプロイ後の確認

### API Gateway エンドポイント取得
```bash
aws cloudformation describe-stacks \
  --stack-name apigw-stack \
  --query 'Stacks[0].Outputs[?OutputKey==`HttpApiEndpoint`].OutputValue' \
  --output text \
  --region ap-northeast-1
```

### CloudFront ドメイン取得
```bash
aws cloudformation describe-stacks \
  --stack-name cloudfront-stack \
  --query 'Stacks[0].Outputs[?OutputKey==`DistributionDomainName`].OutputValue' \
  --output text \
  --region ap-northeast-1
```

### Lambda 関数テスト
```bash
# API Gateway 経由
curl https://<api-gateway-endpoint>/health
curl https://<api-gateway-endpoint>/status

# CloudFront 経由（推奨）
curl https://<cloudfront-domain>/health
curl https://<cloudfront-domain>/status
```

## オプション: AWS Config と Security Hub（コンソール設定）

### AWS Config
CloudFormation でのデプロイが Early Validation エラーで失敗する場合、コンソールで設定。

1. AWS Config コンソールを開く
2. 「設定」→「レコーダーを有効化」
3. 全リソースを記録（グローバルリソース含む）
4. IAM リソースを除外リストに追加（`AWS::IAM::Policy`, `AWS::IAM::User`, `AWS::IAM::Role`, `AWS::IAM::Group`）
5. S3 バケット: `config-snapshots-203553641035-ap-northeast-1`（新規作成またはスタックで作成済みのバケット使用）
6. 配信頻度: 6時間ごと
7. AWS マネージド型ルール（620件）を一括追加（任意）

**CLI での Config 有効化確認**:
```bash
aws configservice describe-configuration-recorders --region ap-northeast-1
aws configservice describe-configuration-recorder-status --region ap-northeast-1
```

### Security Hub（コンソールで設定）
1. Security Hub コンソールを開く
2. 「Security Hub を有効化」
3. 「標準」タブで「AWS 基礎的セキュリティのベストプラクティス v1.0.0」を有効化
4. 初回スキャン完了まで 10-60 分待機

## トラブルシューティング

### Lambda 署名失敗
- S3 バージョニングが有効か確認
- バージョン ID が正しいか確認
- 署名プロファイルが存在するか確認

### Lambda CREATE_FAILED（NoSuchKey）
- `SIGNED_KEY` が正確か確認（`describe-signing-job` で取得推奨）
- `aws s3api head-object --bucket <bucket> --key <key>` で存在確認
- 失敗スタックは削除後に再デプロイ（本手順のリカバリコマンド参照）
- パラメータ名に注意：テンプレートは `CodeS3Key` と `CodeSigningProfileVersionArn` を受け取ります（誤って `LambdaCodeS3Key` / `SignerProfileVersionArn` を渡すとデフォルト `lambda-code/app.zip` が使われて NoSuchKey になります）

### CloudFront デプロイ遅延
- CloudFront ディストリビューションの作成には 15-30 分かかります

### Lambda Reserved Concurrency エラー
- アカウントの同時実行数制限を確認
- 必要なければ `ReservedConcurrency` パラメータを空文字列に設定

### API Gateway アクセスログエラー
- CloudWatch Logs へのアクセス許可を確認
- ログフォーマットがサポートされているか確認

### API Gateway から Lambda への呼び出しが 500 エラー
- API Gateway 統合設定で `CredentialsArn` を使用している場合、Lambda::Permission は不要
- Lambda::Permission を使用する場合は、`CredentialsArn` を削除してください
- Lambda::Permission の SourceArn が API Gateway の呼び出しArnと一致しているか確認
- `$default` ルートの場合、SourceArn は `arn:aws:execute-api:REGION:ACCOUNT:API_ID/STAGE/*` のようにワイルドカード形式で指定してください
- Lambda CloudWatch ログで実際のエラーメッセージを確認
- API Gateway のアクセスログで `integrationError` フィールドにエラーメッセージが記録されているか確認

## スタック削除順序（逆順）
```bash
aws cloudformation delete-stack --stack-name config-stack --region ap-northeast-1
aws cloudformation delete-stack --stack-name monitoring-stack --region ap-northeast-1
aws cloudformation delete-stack --stack-name cloudtrail-stack --region ap-northeast-1
aws cloudformation delete-stack --stack-name cloudfront-stack --region ap-northeast-1
aws cloudformation delete-stack --stack-name lambda-permissions-stack --region ap-northeast-1
aws cloudformation delete-stack --stack-name apigw-stack --region ap-northeast-1
aws cloudformation delete-stack --stack-name lambda-stack --region ap-northeast-1
aws cloudformation delete-stack --stack-name s3-stack --region ap-northeast-1
aws cloudformation delete-stack --stack-name iam-stack --region ap-northeast-1
aws cloudformation delete-stack --stack-name kms-stack --region ap-northeast-1
```

**注意**: 
- S3 バケットは `DeletionPolicy: Retain` のため手動削除が必要です。
- Config をコンソールで設定した場合は CLI で削除:
  ```bash
  aws configservice stop-configuration-recorder --configuration-recorder-name default --region ap-northeast-1
  aws configservice delete-configuration-recorder --configuration-recorder-name default --region ap-northeast-1
  aws configservice delete-delivery-channel --delivery-channel-name default --region ap-northeast-1
  ```
