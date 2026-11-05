# Fork 的 Actions 维护说明

## 日常 CI 和 GHCR 发布

基础测试、代码检查、CodeQL 和 `docker-publish-custom.yml` 不需要新增仓库 Secret。
GHCR 使用 GitHub 自动提供的 `GITHUB_TOKEN`，发布任务已经声明 `packages: write`。
无需手动创建同名 Secret，也无需修改仓库默认只读权限。

推送到 `develop`（包括合并 PR）会自动构建 AMD64 和 ARM64 镜像，发布 `develop-<12 位提交 SHA>`、`sha-<12 位提交 SHA>` 和 `latest` 标签。
正式版本也可以由 `custom-vMAJOR.MINOR.PATCH` 标签或手动输入版本号触发。
已发布的版本不能覆盖；例如 `custom-v1.0.1` 已存在时，需要选择新的未使用版本。
发布工作流目前不检查主 CI 的测试结果，因此发布前应核对同一提交的 CI。

## 本次清理范围

- 删除官方 Algolia 索引、Zendesk、Jira、Slack 邀请检查、LaunchDarkly 同步和 Copybara 同步工作流。
- 删除旧 Docker Hub 发布链、官方 nightly 发布、Cursor 审查和评论命令机器人，包括它们的调用入口。
- 删除官方 SDK 分支对齐检查、上游依赖更新事件入口和仅针对 `fb-` 分支的删除机器人。
- 移除主 CI 中的官方发布、自动生成并回推文档、依赖 `GIT_PAT` 的 Dependabot 自动合并任务。Dependabot 配置仍保留，更新 PR 由维护者审核合并。
- 清理缓存改为仅手动触发；不再每天清空全部缓存。
- 两个只读版本/锁文件检查改用 `github.token`，无需 `GIT_PAT`。
- 删除原本始终禁用的 Codespell 工作流；修正迁移任务的 `head_sha` 输入引用，以及取消任务的 shell 参数传递。

Python/Windows/Conda 测试矩阵、Cypress、Ruff、Biome、Bandit、Gitleaks 和 CodeQL 保留。
现有代码或测试失败需要另行修复，删除官方集成不会使这些失败自动消失。

## 可选：覆盖率展示

只在需要 Codecov 页面时配置：

1. 在 Codecov 中授权 GitHub 并选择 `CorlyDream/label-studio`。
2. 取得该项目的上传 token。
3. 打开仓库 `Settings → Secrets and variables → Actions → Secrets → New repository secret`。
4. 名称填 `CODECOV_TOKEN`，值填上传 token。

不配置时跳过 Codecov 上传，测试仍会执行。`ACTIONS_STEP_DEBUG` 仅用于临时调试，无需常规配置。

## 可选：合并门禁

在本次修改推送并产生检查记录后，进入 `Settings → Rules → Rulesets`：

1. 新建 branch ruleset，目标选择 `develop`，Enforcement status 设为 Active。
2. 启用 Require a pull request before merging。
3. 启用 Require status checks to pass，选择实际生成的 `Ready to merge` 检查。
4. 按维护方式决定是否要求分支与目标分支保持最新。

当前汇总门禁沿用原逻辑：Conda 未列入汇总依赖，PR 汇总允许 Gitleaks 失败。
如要强制这些检查，应单独添加对应 required check 或先调整汇总规则；不要把当前汇总理解为所有任务必须通过。
`Ready to ship` 由 develop 推送触发，不应替代 PR 上的 `Ready to merge`。

## 保留的手动工具

这些工具不再由日常 CI 自动调用，也不是 GHCR 发布的依赖。不使用时无需配置它们。

| 工作流 | 现有要求与限制 |
| --- | --- |
| `release-set-version.yml` | 使用 `GIT_PAT` 回推本仓库版本修改。若启用，token 需具有本仓库 Contents 读写权限，并满足分支规则。 |
| `create-tag-docs.yml` | 使用 `GIT_PAT` 生成并回推标签文档及 schema；同样需要本仓库 Contents 读写权限。 |
| `bump-helm-chart.yml` | 使用 `GIT_PAT` 写入 `CorlyDream/charts`；需先有该仓库及工作流指定的 Chart 路径，token 需具有目标仓库 Contents 读写权限。 |
| `build_pypi.yml` | 保留包构建工具，但默认 release 模式要求 SDK 使用正式版本；当前 git 固定提交不满足此检查。发布仍使用 `label-studio` 包名，不是增加 token 就能发布自己的 fork。 |

如确实使用前三项，可在 GitHub `Settings → Developer settings → Personal access tokens → Fine-grained tokens` 创建限于目标仓库、具有 Contents 读写权限的 token，再按上述 Secret 入口保存为 `GIT_PAT`。不要把 token 写入工作流。
Python 包发布需要另行确定自己的包名、SDK 依赖策略和 PyPI 发布身份，再配置 `PYPI_APIKEY`；本次没有启用或验证这条发布路径。

本次只修改仓库文件；GitHub 上的 Rulesets、Secrets 和其他设置不会随本地修改自动改变。
